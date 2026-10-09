"""Turnstile server validation. Never trust a CAPTCHA completed only in the browser."""

import os

import httpx
from fastapi import HTTPException


def enabled() -> bool:
    # Fail closed if only one of the two variables was configured.
    return bool(
        os.getenv("POWERBID_TURNSTILE_SITE_KEY") or os.getenv("POWERBID_TURNSTILE_SECRET_KEY")
    )


def site_key() -> str:
    return (
        os.getenv("POWERBID_TURNSTILE_SITE_KEY", "")
        if (enabled() and os.getenv("POWERBID_TURNSTILE_SECRET_KEY"))
        else ""
    )


async def verify(token: str | None) -> None:
    if not enabled():
        return
    if not os.getenv("POWERBID_TURNSTILE_SITE_KEY") or not os.getenv(
        "POWERBID_TURNSTILE_SECRET_KEY"
    ):
        raise HTTPException(503, "人机验证配置尚未完成")
    if not token or len(token) > 2048:
        raise HTTPException(422, "请先完成人机验证")
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            result = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": os.environ["POWERBID_TURNSTILE_SECRET_KEY"], "response": token},
            )
            result.raise_for_status()
            outcome = result.json()
        if not outcome.get("success"):
            raise HTTPException(403, "验证已过期或未通过，请重新尝试")
        expected = os.getenv("POWERBID_TURNSTILE_HOSTNAME", "power.smirel.com")
        if outcome.get("hostname") != expected:
            raise HTTPException(403, "验证来源无效")
    except httpx.HTTPError as exc:
        raise HTTPException(503, "人机验证服务暂时不可用，请稍后重试") from exc
