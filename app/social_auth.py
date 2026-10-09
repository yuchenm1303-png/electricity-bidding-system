"""OAuth2 web flows for Google and GitHub, with persistent state and isolated identities."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import account_auth as auth

router = APIRouter(prefix="/api/auth/oauth", tags=["account"])
ORIGIN = "https://power.smirel.com"
PROVIDERS = {
    "google": (
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
        "openid email profile",
    ),
    "github": (
        "https://github.com/login/oauth/authorize",
        "https://github.com/login/oauth/access_token",
        "read:user user:email",
    ),
}


def configured(provider: str) -> bool:
    return (
        provider in PROVIDERS
        and auth.auth_enabled()
        and bool(os.getenv(f"POWERBID_{provider.upper()}_CLIENT_ID"))
        and bool(os.getenv(f"POWERBID_{provider.upper()}_CLIENT_SECRET"))
    )


def callback_url(provider: str) -> str:
    return f"{ORIGIN}/api/auth/oauth/{provider}/callback"


def secure_cookie() -> bool:
    return os.getenv("POWERBID_COOKIE_SECURE", "1") == "1"


def tables(db: sqlite3.Connection) -> None:
    db.executescript("""
      CREATE TABLE IF NOT EXISTS oauth_states(
        digest TEXT PRIMARY KEY, provider TEXT NOT NULL, expires INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS oauth_identities(
        provider TEXT NOT NULL, subject TEXT NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL,
        PRIMARY KEY(provider, subject)
      );
      CREATE UNIQUE INDEX IF NOT EXISTS oauth_user_provider
        ON oauth_identities(provider,user_id);
    """)


def error_redirect(code: str) -> RedirectResponse:
    result = RedirectResponse("/login?auth_error=" + code, status_code=303)
    result.headers["Cache-Control"] = "no-store"
    return result


def erase_state_cookie(response: RedirectResponse, provider: str) -> RedirectResponse:
    response.delete_cookie(
        "pb_oauth_" + provider,
        path=f"/api/auth/oauth/{provider}/callback",
        httponly=True,
        secure=secure_cookie(),
        samesite="lax",
    )
    return response


@router.get("/{provider}/start")
def start(provider: str):
    if provider not in PROVIDERS:
        raise HTTPException(404, "不支持的登录方式")
    if not configured(provider):
        raise HTTPException(503, "该快捷登录尚未配置")
    nonce = secrets.token_urlsafe(32)
    with auth.connection() as db:
        tables(db)
        db.execute("DELETE FROM oauth_states WHERE expires<?", (int(time.time()),))
        db.execute(
            "INSERT INTO oauth_states(digest,provider,expires) VALUES(?,?,?)",
            (hashlib.sha256(nonce.encode()).hexdigest(), provider, int(time.time()) + 600),
        )
    url, _, scope = PROVIDERS[provider]
    query = dict(
        client_id=os.environ[f"POWERBID_{provider.upper()}_CLIENT_ID"],
        redirect_uri=callback_url(provider),
        response_type="code",
        scope=scope,
        state=nonce,
    )
    if provider == "google":
        query["prompt"] = "select_account"
    response = RedirectResponse(url + "?" + urlencode(query), status_code=302)
    response.set_cookie(
        "pb_oauth_" + provider,
        nonce,
        max_age=600,
        httponly=True,
        secure=secure_cookie(),
        samesite="lax",
        path=f"/api/auth/oauth/{provider}/callback",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


async def fetch_identity(provider: str, code: str) -> tuple[str, str]:
    _, token_url, _ = PROVIDERS[provider]
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        result = await client.post(
            token_url,
            headers={"Accept": "application/json"},
            data={
                "client_id": os.environ[f"POWERBID_{provider.upper()}_CLIENT_ID"],
                "client_secret": os.environ[f"POWERBID_{provider.upper()}_CLIENT_SECRET"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": callback_url(provider),
            },
        )
        result.raise_for_status()
        payload = result.json()
        if provider == "google":
            id_token = payload.get("id_token")
            if not isinstance(id_token, str):
                raise ValueError("Missing Google ID token")
            token_info = await client.get(
                "https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token}
            )
            token_info.raise_for_status()
            claims = token_info.json()
            if (
                claims.get("aud") != os.environ["POWERBID_GOOGLE_CLIENT_ID"]
                or claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
                or claims.get("email_verified") not in (True, "true")
            ):
                raise ValueError("Invalid Google identity")
            subject, email = claims.get("sub"), claims.get("email")
        else:
            bearer = payload.get("access_token")
            if not isinstance(bearer, str):
                raise ValueError("Missing GitHub access token")
            headers = {
                "Authorization": "Bearer " + bearer,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            info = await client.get("https://api.github.com/user", headers=headers)
            info.raise_for_status()
            subject = str(info.json().get("id", ""))
            emails = await client.get("https://api.github.com/user/emails", headers=headers)
            emails.raise_for_status()
            available = emails.json()
            email = next(
                (x.get("email") for x in available if x.get("verified") and x.get("primary")), None
            )
            email = email or next((x.get("email") for x in available if x.get("verified")), None)
        if (
            not isinstance(subject, str)
            or not subject
            or not isinstance(email, str)
            or "@" not in email
        ):
            raise ValueError("Verified account identity missing")
        return subject, email.strip().lower()


def resolve_user(provider: str, subject: str, email: str) -> int:
    with auth.connection() as db:
        tables(db)
        db.execute("BEGIN IMMEDIATE")
        user = db.execute(
            "SELECT u.id,u.active FROM oauth_identities o "
            "JOIN users u ON u.id=o.user_id WHERE o.provider=? AND o.subject=?",
            (provider, subject),
        ).fetchone()
        if user:
            if not user["active"]:
                raise PermissionError("disabled")
            return user["id"]
        # Never match email automatically to an existing password or social account.
        if db.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone():
            raise FileExistsError("email_exists")
        if not auth.registration_open():
            raise PermissionError("registration_closed")
        now = int(time.time())
        new = db.execute(
            "INSERT INTO users(username,email,password_hash,role,active,created_at) "
            "VALUES(?,?,?,'member',1,?)",
            (
                provider + "_" + secrets.token_hex(6),
                email,
                auth.HASHER.hash(secrets.token_urlsafe(48)),
                now,
            ),
        )
        db.execute(
            "INSERT INTO oauth_identities(provider,subject,user_id,created_at) VALUES(?,?,?,?)",
            (provider, subject, new.lastrowid, now),
        )
        return new.lastrowid


@router.get("/{provider}/callback")
async def callback(
    provider: str, request: Request, state: str = "", code: str = "", error: str = ""
):
    if provider not in PROVIDERS:
        raise HTTPException(404, "不支持的登录方式")
    rejected = erase_state_cookie(error_redirect("failed"), provider)
    cookie = request.cookies.get("pb_oauth_" + provider, "")
    if (
        not configured(provider)
        or error
        or not code
        or len(code) > 2048
        or not state
        or len(state) > 160
        or not secrets.compare_digest(cookie, state)
    ):
        return rejected
    digest = hashlib.sha256(state.encode()).hexdigest()
    with auth.connection() as db:
        tables(db)
        db.execute("BEGIN IMMEDIATE")
        record = db.execute(
            "SELECT provider,expires FROM oauth_states WHERE digest=?", (digest,)
        ).fetchone()
        if not record or record["provider"] != provider or record["expires"] < int(time.time()):
            return rejected
        db.execute("DELETE FROM oauth_states WHERE digest=?", (digest,))
    try:
        subject, email = await fetch_identity(provider, code)
        user_id = resolve_user(provider, subject, email)
    except FileExistsError:
        return erase_state_cookie(error_redirect("existing_email"), provider)
    except PermissionError:
        return erase_state_cookie(error_redirect("forbidden"), provider)
    except (httpx.HTTPError, ValueError, KeyError, sqlite3.Error):
        return rejected
    response = erase_state_cookie(RedirectResponse("/app", status_code=303), provider)
    auth._set_session(response, user_id)
    return response
