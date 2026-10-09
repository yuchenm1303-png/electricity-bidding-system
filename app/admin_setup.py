"""Admin self-provisioning with a single-use, server-generated invite."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from pydantic import Field

from app import account_auth as auth


class ActivateAdmin(auth.SignUp):
    invite: str = Field(min_length=32, max_length=128)


def mode_is_auto() -> bool:
    return os.getenv("POWERBID_AUTH_ENABLED") == "auto"


def has_admin() -> bool:
    path = auth.db_path()
    if not path.exists():
        return False
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3) as db:
            return (
                db.execute("SELECT 1 FROM users WHERE role='admin' AND active=1 LIMIT 1").fetchone()
                is not None
            )
    except (sqlite3.Error, OSError) as exc:
        # Fail closed on corrupt/inaccessible identity storage: never downgrade
        # to public demo access when checking auth state fails.
        raise RuntimeError("Account database unavailable") from exc


def setup_available() -> bool:
    return os.getenv("POWERBID_ADMIN_SETUP_ENABLED") == "1" and not has_admin()


@auth.router.post("/setup-admin", status_code=201)
def activate_admin(data: ActivateAdmin, response: Response, request: Request) -> dict:
    # Only the administrator's expiring, single-use invite can authorize this route.
    if not mode_is_auto() or not setup_available():
        raise HTTPException(403, detail="管理员初始化不可用")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower():
        raise HTTPException(403, detail="跨站请求被拒绝")
    if request.headers.get("x-powerbid-request") != "1":
        raise HTTPException(403, detail="请求缺少安全标记")
    username = data.username.strip()
    if not auth.USERNAME.fullmatch(username):
        raise HTTPException(422, detail="用户名必须以字母开头，只能包含字母、数字、下划线和连字符")
    digest = hashlib.sha256(data.invite.encode("utf-8")).hexdigest()
    now = int(time.time())
    # A write lock makes token redemption and first-administrator creation atomic.
    with auth.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT token_hash, expires_at FROM admin_setup WHERE id=1"
        ).fetchone()
        admin_exists = db.execute(
            "SELECT id FROM users WHERE role='admin' LIMIT 1"
        ).fetchone()
        valid = (
            row is not None
            and row["expires_at"] > now
            and hmac.compare_digest(row["token_hash"], digest)
        )
        if admin_exists or not valid:
            raise HTTPException(403, detail="激活链接无效或已过期")
        password_hash = auth.HASHER.hash(data.password)
        cursor = db.execute(
            "INSERT INTO users(username,email,password_hash,role,active,created_at) "
            "VALUES(?,?,?,'admin',1,?)",
            (username, str(data.email).lower(), password_hash, now),
        )
        db.execute("DELETE FROM admin_setup WHERE id=1")
        user_id = cursor.lastrowid
    # After the above transaction commits, auto mode enables authentication.
    auth._set_session(response, user_id)
    return {
        "id": user_id,
        "username": username,
        "email": str(data.email).lower(),
        "role": "admin",
        "active": True,
    }


def issue_invite(hours: int = 24) -> str:
    if not mode_is_auto() or os.getenv("POWERBID_ADMIN_SETUP_ENABLED") != "1":
        raise RuntimeError("Activate auto mode and admin setup flag before issuing an invite")
    if has_admin():
        raise RuntimeError("Administrator already exists; cannot issue another bootstrap invite")
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with auth.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone():
            raise RuntimeError("Administrator already exists")
        db.execute(
            "CREATE TABLE IF NOT EXISTS admin_setup("
            "id INTEGER PRIMARY KEY CHECK(id=1), token_hash TEXT NOT NULL, "
            "expires_at INTEGER NOT NULL)"
        )
        db.execute(
            "INSERT INTO admin_setup(id, token_hash, expires_at) VALUES(1,?,?) "
            "ON CONFLICT(id) DO UPDATE SET token_hash=excluded.token_hash, "
            "expires_at=excluded.expires_at",
            (digest, int(time.time()) + hours * 3600),
        )
    # Fragment does not travel in HTTP requests, browser referrer or reverse proxy logs.
    return "https://power.smirel.com/setup-admin#" + token
