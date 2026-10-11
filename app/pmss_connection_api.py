"""PowerBid authenticated members' bounded shared PMSS/VPN connection controls.

Never accept a command, container name, URL or credentials from the browser.
The optional Unix-socket operator owns *only* the exact EasyConnect container.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest
from urllib.request import urlopen

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.account_auth import require_user

router = APIRouter(prefix="/api/pmss/connection", tags=["pmss-connection"])
_OPERATOR_SOCKET = "/run/powerbid-vpn/vpn.sock"
_BRIDGE_URL = "http://172.17.0.1:18760"
_HEADERS = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_PROBE_LOCK = threading.Lock()
_PROBE_CACHE: tuple[float, str] = (0.0, "unknown")


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path: str):
        super().__init__("localhost", timeout=2.5)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


def _operator(method: str, path: str) -> dict:
    if not os.path.exists(_OPERATOR_SOCKET):
        raise OSError("The VPN operator socket is not provisioned")
    connection = _UnixHTTP(_OPERATOR_SOCKET)
    try:
        connection.request(method, path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(4096)
        result = json.loads(body)
        if not isinstance(result, dict):
            raise OSError("Invalid operator response")
        if response.status >= 400:
            raise RuntimeError(str(result.get("code", "operator_unavailable")))
        return result
    finally:
        connection.close()


def _probe_bridge() -> str:
    """Check upstream read authorization; bridge /health only proves cookies exist."""
    global _PROBE_CACHE
    with _PROBE_LOCK:
        now = time.monotonic()
        if now - _PROBE_CACHE[0] < 25:
            return _PROBE_CACHE[1]
        outcome = "unknown"
        try:
            query = (
                "/pmss/web/project/list?permissionType=0&projectType=1"
                "&pageSize=1&pageNo=1&version=base"
            )
            request = URLRequest(
                _BRIDGE_URL + query,
                headers={"Accept": "application/json"},
                method="GET",
            )
            with urlopen(request, timeout=3.5) as response:
                if response.status == 200:
                    data = json.loads(response.read(16384))
                    if isinstance(data, dict):
                        if data.get("retCode") == "T200":
                            outcome = "authorized"
                        elif data.get("retCode") == "T000":
                            outcome = "login_required"
        except HTTPError:
            # An upstream HTTP response is not proof of a VPN transport outage.
            pass
        except (OSError, URLError, TimeoutError):
            outcome = "unreachable"
        except ValueError:
            pass
        _PROBE_CACHE = (time.monotonic(), outcome)
        return outcome


def _response(data: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=data, headers=_HEADERS)


@router.get("/status")
def connection_status(request: Request):
    user = require_user(request)
    operator_state = "unavailable"
    container = "unknown"
    cooldown = 0
    try:
        details = _operator("GET", "/status")
        operator_state = "ready"
        container = "running" if details.get("running") is True else "stopped"
        cooldown = int(details.get("retry_after_seconds", 0))
    except (OSError, RuntimeError, ValueError, KeyError):
        pass
    pmss_access = _probe_bridge()
    return _response({
        "operator": operator_state,
        "vpn_container": container,
        "pmss_access": pmss_access,
        "shared_connection": True,
        "reconnect_allowed": (
            user["role"] == "admin" and operator_state == "ready"
            and pmss_access == "unreachable" and cooldown == 0
        ),
        "retry_after_seconds": max(0, min(cooldown, 3600)),
        "private_case_catalog": (
            "configured" if (Path("/private/powerbid-pmss") / "catalog.json").is_file()
            else "not_configured"
        ),
        "external_login_url": "https://vpn.tsintergy.com:4434/portal/",
        "external_login_is_server_session": False,
        "writes_to_teacher_platform": False,
    })


@router.post("/reconnect")
async def reconnect(request: Request):
    # No caller may pick a container, command, URL, or credentials.
    require_user(request, admin=True)
    if await request.body():
        raise HTTPException(422, detail="重连请求不接受任何参数")
    access = _probe_bridge()
    if access == "authorized":
        raise HTTPException(409, detail="服务器 PMSS 连接正常，禁止中断其他用户")
    if access == "login_required":
        raise HTTPException(409, detail="学校平台需要重新认证，重启 VPN 无法替代登录")
    if access != "unreachable":
        raise HTTPException(503, detail="尚未确认 VPN 断线，请稍后重新检测")
    try:
        result = _operator("POST", "/reconnect")
    except RuntimeError as exc:
        if "rate_limited" in str(exc):
            raise HTTPException(429, detail="重连冷却中，请稍后再试") from None
        raise HTTPException(503, detail="服务器 VPN 重连服务暂不可用") from None
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, detail="服务器 VPN 重连服务尚未就绪") from None
    if result.get("restart_requested") is not True:
        raise HTTPException(503, detail="未能执行服务器 VPN 重连")
    global _PROBE_CACHE
    with _PROBE_LOCK:
        _PROBE_CACHE = (0.0, "unknown")
    return _response({
        "restart_requested": True,
        "vpn_authenticated": False,
        "message": "共享 VPN 已尝试重启；需要学校重新认证时，仍须获授权的使用者完成登录。",
    })
