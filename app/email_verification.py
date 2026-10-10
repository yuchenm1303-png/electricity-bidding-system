"""Verified email registration via the existing Resend sending service.

The six-digit code is HMAC-protected at rest. Per-address, IP and global
rate limits are persisted in the same SQLite database as PowerBid accounts.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app import account_auth as auth
from app.turnstile_auth import verify as verify_turnstile

router = APIRouter(prefix="/api/auth/email", tags=["account"])
CODE_TTL = 10 * 60
COOLDOWN = 60
MAX_GUESSES = 5


def required() -> bool:
    return os.getenv("POWERBID_EMAIL_VERIFICATION_ENABLED", "0") == "1"


def configured() -> bool:
    return all(
        os.getenv(key)
        for key in ("POWERBID_RESEND_API_KEY", "POWERBID_EMAIL_FROM", "POWERBID_EMAIL_CODE_SECRET")
    )


def _secret() -> bytes:
    if not configured():
        raise HTTPException(503, detail="邮件验证服务尚未配置")
    return os.environ["POWERBID_EMAIL_CODE_SECRET"].encode()


def _digest(email: str, code: str) -> str:
    return hmac.new(_secret(), f"{email.lower()}\x00{code}".encode(), hashlib.sha256).hexdigest()


def _hash(value: str) -> str:
    return hmac.new(_secret(), value.encode(), hashlib.sha256).hexdigest()


class SendCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    turnstile_token: Annotated[str | None, Field(max_length=2048)] = None


def _rate_limit(db: sqlite3.Connection, email: str, ip: str, now: int) -> None:
    email_hash = _hash(email)
    ip_hash = _hash(ip)
    db.execute("DELETE FROM email_send_events WHERE sent_at<?", (now - 86400,))
    latest = db.execute(
        "SELECT last_sent_at FROM email_verification_codes WHERE email=?", (email,)
    ).fetchone()
    if latest and now - latest["last_sent_at"] < COOLDOWN:
        raise HTTPException(429, detail="请在 60 秒后重新发送验证码")
    # Bound abuse even without Turnstile configured.
    for query, values, ceiling in [
        ("email_hash=? AND sent_at>=?", (email_hash, now - 3600), 5),
        ("ip_hash=? AND sent_at>=?", (ip_hash, now - 3600), 40),
        ("sent_at>=?", (now - 3600,), 30),
        ("sent_at>=?", (now - 86400,), 80),
    ]:
        count = db.execute(
            f"SELECT count(*) FROM email_send_events WHERE {query}", values
        ).fetchone()[0]
        if count >= ceiling:
            raise HTTPException(429, detail="验证码请求过于频繁，请稍后重试")


async def _deliver(email: str, code: str) -> None:
    key = os.environ["POWERBID_RESEND_API_KEY"]
    sender = os.environ["POWERBID_EMAIL_FROM"]
    html = (
        '<div style="font-family:system-ui,sans-serif;max-width:540px;margin:auto;'
        'color:#182337;padding:24px">'
        "<h2>PowerBid 邮箱验证</h2>"
        "<p>正在创建电力报价系统账号。以下为本次注册的六位验证码：</p>"
        f'<p style="font-size:36px;font-weight:700;letter-spacing:8px">{code}</p>'
        "<p>验证码十分钟内有效，且只能使用一次。</p>"
        '<p style="color:#778399;font-size:12px">如果你没有注册 PowerBid，请忽略此邮件。</p>'
        "</div>"
    )
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "from": sender,
                    "to": [email],
                    "subject": "PowerBid · 邮箱验证码",
                    "html": html,
                    "text": f"PowerBid 验证码：{code}。十分钟内有效，仅可使用一次。",
                },
            )
        response.raise_for_status()
        if not response.json().get("id"):
            raise ValueError("Resend did not confirm message acceptance")
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, detail="邮件暂时发送失败，请稍后重试") from exc


@router.post("/send-code")
async def send_code(body: SendCode, request: Request) -> dict[str, str]:
    if not auth.auth_enabled() or not auth.registration_open():
        raise HTTPException(403, detail="当前未开放新账号注册")
    if not required() or not configured():
        raise HTTPException(503, detail="邮箱验证码暂不可用")
    await verify_turnstile(body.turnstile_token)

    email = str(body.email).strip().lower()
    now = int(time.time())
    client_ip = request.client.host if request.client else "unknown"
    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = _digest(email, code)
    already_registered = False
    # Reserve quota before calling the mail provider. Never reveal whether an
    # email belongs to an existing account.
    with auth.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        _rate_limit(db, email, client_ip, now)
        db.execute(
            "INSERT INTO email_send_events(email_hash,ip_hash,sent_at) VALUES(?,?,?)",
            (_hash(email), _hash(client_ip), now),
        )
        already_registered = (
            db.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
            is not None
        )
        if not already_registered:
            db.execute(
                "INSERT INTO email_verification_codes"
                "(email,code_hash,expires_at,last_sent_at,failed_attempts) VALUES(?,?,?,?,0) "
                "ON CONFLICT(email) DO UPDATE SET code_hash=excluded.code_hash,"
                "expires_at=excluded.expires_at,last_sent_at=excluded.last_sent_at,"
                "failed_attempts=0",
                (email, digest, now + CODE_TTL, now),
            )
    if not already_registered:
        try:
            await _deliver(email, code)
        except HTTPException:
            # A failed send must not leave a code that the recipient never received.
            with auth.connection() as db:
                db.execute(
                    "DELETE FROM email_verification_codes WHERE email=? AND code_hash=?",
                    (email, digest),
                )
            raise
    return {"message": "如果该邮箱可以注册，验证码将发送到你的收件箱"}


def check_code(db: sqlite3.Connection, email: str, code: str | None) -> None:
    if not required():
        return
    if not configured():
        raise HTTPException(503, detail="邮箱验证服务尚未配置")
    if not code or len(code) != 6 or not code.isdecimal():
        raise HTTPException(422, detail="请填写六位邮箱验证码")
    record = db.execute(
        "SELECT code_hash,expires_at,failed_attempts FROM email_verification_codes "
        "WHERE email=? COLLATE NOCASE",
        (email,),
    ).fetchone()
    if (
        not record
        or record["expires_at"] <= int(time.time())
        or record["failed_attempts"] >= MAX_GUESSES
    ):
        raise HTTPException(403, detail="验证码无效或已过期，请重新获取")
    if not hmac.compare_digest(record["code_hash"], _digest(email, code)):
        db.execute(
            "UPDATE email_verification_codes SET failed_attempts=failed_attempts+1 WHERE email=?",
            (email,),
        )
        db.commit()
        raise HTTPException(403, detail="验证码错误，请重新确认")
    # Caller consumes the code in the same transaction as account insertion.
