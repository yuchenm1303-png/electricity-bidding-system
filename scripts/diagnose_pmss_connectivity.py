"""Diagnose PMSS transport without authentication or any market operations.

This never reads cookies, tokens, case IDs or PMSS API records.
It sends HEAD requests only to the user-selected page and a known public
control. Its JSON output deliberately omits hostnames, URLs, IPs and stderr.
HTTP 401/403 still proves reachability; they are NOT authentication success.
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

PUBLIC_CONTROL = "https://example.com"
DEFAULT_PROXY = "socks5h://127.0.0.1:11080"


@dataclass(frozen=True, slots=True)
class Probe:
    transport_reachable: bool
    http_status: int | None
    curl_exit_code: int
    # All errors are represented by a category, never response details.
    fault_category: str


def validate_target(raw: str) -> str:
    if not isinstance(raw, str) or any(ord(char) < 33 for char in raw):
        raise ValueError("Target URL must be an unambiguous HTTP(S) URL")
    url = urlsplit(raw)
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
    ):
        raise ValueError("Supply an HTTP(S) PMSS page URL without credentials or query")
    try:
        _ = url.port
    except ValueError as exc:
        raise ValueError("Invalid target port") from exc
    return raw


def validate_proxy(raw: str) -> tuple[str, int]:
    url = urlsplit(raw)
    if (
        url.scheme != "socks5h"
        or url.hostname not in {"127.0.0.1", "localhost"}
        or not url.port
        or url.username is not None
        or url.password is not None
        or url.path
        or url.query
        or url.fragment
    ):
        raise ValueError("Only a local unauthenticated socks5h:// proxy is supported")
    return url.hostname, url.port


def _fault(exit_code: int) -> str:
    return {
        0: "none",
        5: "proxy_dns",
        6: "target_dns",
        7: "tcp_connect_failed",
        28: "network_timeout",
        35: "tls_failure",
        52: "empty_reply",
        56: "recv_failure",
        60: "certificate_verification",
        97: "socks_handshake",
    }.get(exit_code, "other_transport_failure")


def _check_proxy_local(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=min(timeout, 2.0)):
            return True
    except OSError:
        return False


def _head(url: str, *, proxy: str | None, timeout: int) -> Probe:
    """Never follow redirects or print their Location (may contain secrets)."""
    command = [
        "curl", "--silent", "--show-error", "--head",
        "--connect-timeout", str(min(timeout, 4)),
        "--max-time", str(timeout),
        "--output", "/dev/null",
        "--write-out", "%{http_code}",
    ]
    if proxy is None:
        command.extend(["--noproxy", "*"])
    else:
        command.extend(["--proxy", proxy, "--noproxy", ""])
    command.append(url)
    try:
        done = subprocess.run(
            command, capture_output=True, text=True,
            check=False, timeout=timeout + 3,
        )
    except subprocess.TimeoutExpired:
        return Probe(False, None, 28, "network_timeout")
    status = int(done.stdout.strip()) if done.stdout.strip().isdigit() else 0
    return Probe(
        transport_reachable=bool(status),
        http_status=status if status else None,
        curl_exit_code=done.returncode,
        fault_category=_fault(done.returncode),
    )


def diagnose(target_url: str, *, proxy_url: str = DEFAULT_PROXY, timeout: int = 7) -> dict:
    target = validate_target(target_url)
    host, port = validate_proxy(proxy_url)
    if type(timeout) is not int or not 3 <= timeout <= 20:
        raise ValueError("Timeout must be 3..20 seconds")
    if not shutil.which("curl"):
        raise ValueError("curl is required on the trusted server")
    proxy_socket = _check_proxy_local(host, port, timeout)
    direct_public = _head(PUBLIC_CONTROL, proxy=None, timeout=timeout)
    proxy_public = (
        _head(PUBLIC_CONTROL, proxy=proxy_url, timeout=timeout)
        if proxy_socket else Probe(False, None, 7, "tcp_connect_failed")
    )
    proxy_target = (
        _head(target, proxy=proxy_url, timeout=timeout)
        if proxy_socket else Probe(False, None, 7, "tcp_connect_failed")
    )
    # Direct private transport is supplemental and can be blocked intentionally.
    direct_target = _head(target, proxy=None, timeout=timeout)
    if proxy_target.transport_reachable:
        state = "PRIVATE_ENDPOINT_REACHABLE"
        action = "Read-only PMSS API checks may resume; authentication is unverified."
    elif not proxy_socket:
        state = "LOCAL_PROXY_UNAVAILABLE"
        action = "Inspect local SOCKS listener and EasyConnect container."
    elif proxy_public.transport_reachable and not proxy_target.transport_reachable:
        state = "PUBLIC_PROXY_OK_PRIVATE_TARGET_UNREACHABLE"
        action = (
            "Proxy is alive, but does not reach PMSS. Check VPN authentication, "
            "private routes and school gateway; do not submit or clear bids."
        )
    elif not direct_public.transport_reachable:
        state = "HOST_PUBLIC_CONNECTIVITY_UNAVAILABLE"
        action = "Check host internet connectivity before diagnosing PMSS login."
    else:
        state = "PROXY_UPSTREAM_UNAVAILABLE"
        action = "Check EasyConnect session, local SOCKS routing and VPN gateway."
    return {
        "state": state,
        "proxy_tcp_listening": proxy_socket,
        "public_direct": asdict(direct_public),
        "public_via_proxy": asdict(proxy_public),
        "pmss_via_proxy": asdict(proxy_target),
        "pmss_direct": asdict(direct_target),
        "safe_action": action,
        "checks_are_read_only": True,
        "teacher_login_verified": False,
        "pmss_market_write_performed": False,
        "pmss_clearing_executed": False,
        "target_address_disclosed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Credential-free PMSS VPN path diagnosis")
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--proxy", default=DEFAULT_PROXY)
    parser.add_argument("--timeout", type=int, default=7)
    args = parser.parse_args()
    try:
        data = diagnose(args.target_url, proxy_url=args.proxy, timeout=args.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0 if data["state"] == "PRIVATE_ENDPOINT_REACHABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
