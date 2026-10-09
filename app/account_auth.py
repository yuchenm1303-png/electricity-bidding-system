"""Optional, persistent account system for PowerBid.

- Accounts are not enabled in production until explicitly configured.
- All passwords use Argon2id; sessions are opaque, hashed tokens in SQLite.
- First admin is provisioned ONLY from the console, never by public signup.
- SQLite file MUST live in a mounted persistent directory in production.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

COOKIE = "powerbid_session"
TTL = 7 * 86400
HASHER = PasswordHasher(time_cost=3, memory_cost=32768, parallelism=2)
USERNAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{2,31}$")
router = APIRouter(prefix="/api/auth", tags=["account"])


def auth_enabled() -> bool:
    return os.getenv("POWERBID_AUTH_ENABLED", "0") == "1"


def registration_open() -> bool:
    return os.getenv("POWERBID_REGISTRATION_OPEN", "0") == "1"


def db_path() -> Path:
    return Path(os.environ.get("POWERBID_AUTH_DB_PATH", "/data/powerbid-accounts.sqlite3"))


@contextmanager
def connection():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(str(path), timeout=10)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE COLLATE NOCASE,
              email TEXT NOT NULL UNIQUE COLLATE NOCASE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('admin', 'member')),
              active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              expires_at INTEGER NOT NULL,
              created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_by_user ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS login_attempts (
              username TEXT PRIMARY KEY COLLATE NOCASE,
              fail_count INTEGER NOT NULL,
              locked_until INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );
        """)
        if path.exists():
            os.chmod(path, 0o600)
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def serialize(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
    }


def find_session(request: Request) -> dict | None:
    if not auth_enabled():
        return None
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 180:
        return None
    token_hash = hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()
    with connection() as db:
        row = db.execute(
            """SELECT users.* FROM sessions
               JOIN users ON sessions.user_id=users.id
               WHERE token_hash=? AND expires_at>? AND users.active=1""",
            (token_hash, int(time.time())),
        ).fetchone()
    return serialize(row) if row else None


def require_user(request: Request, admin: bool = False) -> dict:
    if not auth_enabled():
        raise HTTPException(503, detail="账号系统尚未启用")
    user = find_session(request)
    if user is None:
        raise HTTPException(401, detail="请先登录")
    if admin and user["role"] != "admin":
        raise HTTPException(403, detail="需要管理员权限")
    return user


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=12, max_length=128)


class SignUp(Credentials):
    email: EmailStr


def _set_session(response: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    timestamp = int(time.time())
    with connection() as db:
        db.execute("DELETE FROM sessions WHERE expires_at<=?", (timestamp,))
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, timestamp + TTL, timestamp),
        )
    response.set_cookie(
        key=COOKIE,
        value=token,
        httponly=True,
        secure=os.getenv("POWERBID_COOKIE_SECURE", "1") == "1",
        samesite="lax",
        max_age=TTL,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/config")
def config() -> dict:
    return {
        "enabled": auth_enabled(),
        "registration_open": auth_enabled() and registration_open(),
    }


@router.post("/register", status_code=201)
def register(data: SignUp, response: Response) -> dict:
    if not auth_enabled() or not registration_open():
        raise HTTPException(403, detail="管理员尚未开放注册")
    username = data.username.strip()
    email = str(data.email).lower()
    if not USERNAME.fullmatch(username):
        raise HTTPException(422, detail="用户名必须以字母开头，只能包含字母、数字、下划线和连字符")
    password_hash = HASHER.hash(data.password)
    with connection() as db:
        try:
            cursor = db.execute(
                "INSERT INTO users(username,email,password_hash,role,active,created_at) VALUES(?,?,?,'member',1,?)",
                (username, email, password_hash, int(time.time())),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, detail="用户名或邮箱已被使用") from exc
        user_id = cursor.lastrowid
    _set_session(response, user_id)
    return {"id": user_id, "username": username, "email": email, "role": "member", "active": True}


@router.post("/login")
def login(data: Credentials, response: Response) -> dict:
    if not auth_enabled():
        raise HTTPException(503, detail="账号系统尚未启用")
    name = data.username.strip()
    timestamp = int(time.time())
    with connection() as db:
        lock = db.execute(
            "SELECT fail_count, locked_until, updated_at FROM login_attempts WHERE username=?", (name,)
        ).fetchone()
        if lock and lock["locked_until"] > timestamp:
            raise HTTPException(429, detail="尝试次数过多，请稍后重试")
        row = db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (name,)).fetchone()
        verified = False
        if row and row["active"]:
            try:
                verified = HASHER.verify(row["password_hash"], data.password)
            except (VerifyMismatchError, VerificationError):
                verified = False
        else:
            # Same expensive operation for nonexistent users reduces username enumeration.
            try:
                HASHER.verify(DUMMY_HASH, data.password)
            except (VerifyMismatchError, VerificationError):
                pass
        if not verified:
            count = (lock["fail_count"] + 1) if lock and timestamp - lock["updated_at"] < 900 else 1
            until = timestamp + 900 if count >= 5 else 0
            db.execute(
                """INSERT INTO login_attempts(username,fail_count,locked_until,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(username) DO UPDATE SET fail_count=excluded.fail_count,
                locked_until=excluded.locked_until,updated_at=excluded.updated_at""",
                (name, count, until, timestamp),
            )
            db.commit()  # Persist the failed-attempt counter before returning an error.
            raise HTTPException(401, detail="用户名或密码错误")
        db.execute("DELETE FROM login_attempts WHERE username=?", (name,))
        user = serialize(row)
    _set_session(response, user["id"])
    return user


# A static Argon2 hash of a non-secret dummy password; never used for authentication.
DUMMY_HASH = HASHER.hash("powerbid-nonexistent-user-sentinel")


@router.get("/me")
def me(request: Request) -> dict:
    return require_user(request)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE, "")
    if token:
        with connection() as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (hashlib.sha256(token.encode("ascii", "ignore")).hexdigest(),),
            )
    response.delete_cookie(
        COOKIE, path="/", secure=os.getenv("POWERBID_COOKIE_SECURE", "1") == "1",
        httponly=True, samesite="lax",
    )
    return {"ok": True}


@router.get("/users")
def users(request: Request) -> list[dict]:
    require_user(request, admin=True)
    with connection() as db:
        return [serialize(row) for row in db.execute("SELECT * FROM users ORDER BY id DESC LIMIT 200")]


@router.post("/users/{user_id}/enabled")
def set_enabled(user_id: int, data: dict[str, bool], request: Request) -> dict:
    admin = require_user(request, admin=True)
    if set(data) != {"enabled"} or not isinstance(data.get("enabled"), bool):
        raise HTTPException(422, detail="enabled 参数必须是布尔值")
    if admin["id"] == user_id and not data["enabled"]:
        raise HTTPException(400, detail="不能禁用自己的管理员账号")
    with connection() as db:
        result = db.execute("UPDATE users SET active=? WHERE id=?", (int(data["enabled"]), user_id))
        if not result.rowcount:
            raise HTTPException(404, detail="用户不存在")
        if not data["enabled"]:
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    return {"id": user_id, "active": data["enabled"]}


async def protect_api(request: Request, call_next):
    if request.url.path.startswith("/api/") and auth_enabled():
        path = request.url.path
        publicly_accessible = path in {
            "/api/health", "/api/auth/config", "/api/auth/login",
            "/api/auth/register", "/api/auth/logout",
        }
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower():
                return JSONResponse({"detail": "跨站请求被拒绝"}, status_code=403)
            if request.headers.get("x-powerbid-request") != "1":
                return JSONResponse({"detail": "请求缺少安全标记"}, status_code=403)
        if not publicly_accessible and find_session(request) is None:
            return JSONResponse({"detail": "请先登录"}, status_code=401)
    return await call_next(request)


def bootstrap_admin(username: str, email: str) -> None:
    if not USERNAME.fullmatch(username):
        raise ValueError("Invalid username")
    password = getpass.getpass("New administrator password (at least 12 characters): ")
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Password must be 12–128 characters")
    password_hash = HASHER.hash(password)
    with connection() as db:
        if db.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone():
            raise RuntimeError("Admin already exists; refusing a second automatic bootstrap")
        db.execute(
            "INSERT INTO users(username,email,password_hash,role,active,created_at) VALUES(?,?,?,'admin',1,?)",
            (username, email.lower(), password_hash, int(time.time())),
        )
    print("Administrator created. No password was printed or logged.")


def main() -> None:
    parser = argparse.ArgumentParser(description="PowerBid account administration")
    parser.add_argument("command", choices=["bootstrap-admin"])
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    if args.command == "bootstrap-admin":
        bootstrap_admin(args.username, args.email)


if __name__ == "__main__":
    main()
