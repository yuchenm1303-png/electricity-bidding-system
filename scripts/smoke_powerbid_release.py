"""Safe end-to-end production parity probe for the PowerBid research console.

Detect lazy-loaded Vite workspace bundles (not only the index script).
Verify both history audit and manual-result handoff UI plus FastAPI routes.
The manual handoff route is checked via public OpenAPI metadata only;
no operator confirmation or school PMSS call is made.

No PMSS teacher connection or credentials. All HTTP requests are bounded.
The only POST is an intentionally invalid JSON payload to our OWN audit
endpoint; it must return 422 without any market/clearing side effects.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import deque
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_JS_REFERENCE = re.compile(
    r"""["']((?:/assets/|assets/|\./)[A-Za-z0-9._/-]+\.js)["']"""
)
_HTML_MODULE = re.compile(
    r"""<script\b[^>]*\btype=["']module["'][^>]*\bsrc=["'](/assets/[A-Za-z0-9._-]+\.js)["']""",
    re.IGNORECASE,
)
_HEALTH = "/api/health"
_OPENAPI = "/openapi.json"
_GATE = "/api/pmss/holdout-gate"
_HANDOFF = "/api/pmss/manual-clearing-review"
_MAX_ASSETS = 24
_MAX_BYTES = 4_000_000


class RedirectsForbidden(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _origin(raw: str) -> str:
    if not isinstance(raw, str):
        raise ValueError("Invalid PowerBid production origin")
    try:
        url = urlsplit(raw)
        _ = url.port
    except ValueError as exc:
        raise ValueError("Invalid PowerBid production origin") from exc
    if (
        url.scheme not in ("https", "http")
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.path not in ("", "/")
        or url.query or url.fragment
        or len(raw) > 250
    ):
        raise ValueError("Require a bare, explicit PowerBid HTTP(S) origin")
    if url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Production smoke test requires HTTPS")
    return raw.rstrip("/")


def _request(origin: str, path: str, method: str = "GET") -> tuple[int, bytes]:
    if not path.startswith("/") or "//" in path or ".." in path:
        raise ValueError("Only same-origin paths are accepted")
    data = b'{"report":{}}' if method == "POST" else None
    req = Request(
        origin + path,
        method=method, data=data,
        headers={
            "User-Agent": "PowerBid-Safe-Release-Check/1.0",
            "Accept": "application/json" if path.startswith("/api/") or path == _OPENAPI
            else "text/html,application/javascript",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    opener = build_opener(RedirectsForbidden())
    try:
        with opener.open(req, timeout=8) as resp:
            if resp.status >= 300:
                raise ValueError("Unexpected PowerBid response status")
            body = resp.read(_MAX_BYTES + 1)
            if len(body) > _MAX_BYTES:
                raise ValueError("PowerBid asset exceeds safe response limit")
            return resp.status, body
    except HTTPError as exc:
        # HTTP errors are statuses, not exceptions for the 422 validation probe.
        # Deliberately do not read or return server-generated error bodies.
        return exc.code, b""


def _js_path(href: str, parent: str) -> str:
    if (
        not re.fullmatch(
            r"(?:/assets/|assets/|\./)[A-Za-z0-9._/-]+\.js", href
        ) or ".." in href.split("/") or "//" in href
    ):
        raise ValueError("Unsafe JavaScript asset reference")
    if href.startswith("/assets/"):
        candidate = href
    elif href.startswith("assets/"):
        candidate = "/" + href
    else:
        candidate = str(PurePosixPath(parent).parent.joinpath(href))
    parts = PurePosixPath(candidate).parts
    if (
        not candidate.startswith("/assets/")
        or not candidate.endswith(".js")
        or any(p in (".", "..") for p in parts)
    ):
        raise ValueError("Unsafe JavaScript asset reference")
    return candidate


def inspect_powerbid_release(
    origin: str,
    *,
    fetcher: Callable[[str, str, str], tuple[int, bytes]] = _request,
) -> dict[str, Any]:
    """Inspect public app artifacts and safe error-validation behavior.

    Missing or inconsistent assets are a deployment problem; they are not
    interpreted as defects or availability of the teacher's PMSS system.
    """
    target = _origin(origin)
    root_status, html_bytes = fetcher(target, "/", "GET")
    if root_status != 200:
        raise ValueError("Production homepage is unavailable")
    html = html_bytes.decode("utf-8", errors="replace")
    first = _HTML_MODULE.findall(html)
    if not first:
        raise ValueError("Production HTML lacks a Vite module entrypoint")

    discovered = deque(_js_path(path, "/") for path in first)
    checked: set[str] = set()
    found_gate = False
    found_title = False
    found_handoff_endpoint = False
    found_handoff_title = False
    while discovered and len(checked) < _MAX_ASSETS:
        asset = discovered.popleft()
        if asset in checked:
            continue
        checked.add(asset)
        status, blob = fetcher(target, asset, "GET")
        if status != 200:
            raise ValueError("Production lazy-loaded JavaScript chunk is unavailable")
        source = blob.decode("utf-8", errors="replace")
        found_gate |= "holdout-gate" in source
        found_title |= "历史分配规则" in source
        found_handoff_endpoint |= "manual-clearing-review" in source
        found_handoff_title |= "报价与老师出清结果" in source
        if (found_gate and found_title and found_handoff_endpoint
                and found_handoff_title):
            break
        for match in _JS_REFERENCE.finditer(source):
            child = _js_path(match.group(1), asset)
            if child not in checked:
                discovered.append(child)
    if not found_gate or not found_title:
        raise ValueError(
            "Frontend release lacks the anonymous historical holdout UI "
            "in its entrypoint or reachable lazy-loaded chunks"
        )

    if not found_handoff_endpoint or not found_handoff_title:
        raise ValueError(
            "Frontend release lacks the manual-clearing handoff UI "
            "in its reachable lazy-loaded chunks"
        )

    health_status, health_bytes = fetcher(target, _HEALTH, "GET")
    if health_status != 200:
        raise ValueError("PowerBid health endpoint unavailable")
    health = json.loads(health_bytes)
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise ValueError("PowerBid API health payload invalid")
    schema_status, schema_bytes = fetcher(target, _OPENAPI, "GET")
    if schema_status != 200:
        raise ValueError("PowerBid public OpenAPI metadata unavailable")
    schema = json.loads(schema_bytes)
    route = schema.get("paths", {}).get(_GATE)
    if not isinstance(route, dict) or "post" not in route:
        raise ValueError("Production OpenAPI lacks the holdout POST handler")

    handoff_route = schema.get("paths", {}).get(_HANDOFF)
    if not isinstance(handoff_route, dict) or "post" not in handoff_route:
        raise ValueError("Production OpenAPI lacks the manual-clearing POST handler")

    invalid_post_status, _ = fetcher(target, _GATE, "POST")
    if invalid_post_status != 422:
        raise ValueError(
            "Production holdout API did not reject an invalid research report"
        )
    return {
        "state": "FRONTEND_BACKEND_HOLDOUT_PARITY_VERIFIED",
        "frontendLazyChunkDiscovered": True,
        "frontendHistoryGatePresent": True,
        "backendPostRoutePresent": True,
        "manualClearingFrontendPresent": True,
        "manualClearingBackendPostRoutePresent": True,
        "invalidResearchReportRejected": True,
        "productionMainHeadVerified": False,
        "teacherPMSSAuthenticated": False,
        "originalHistoricalInputsInspected": False,
        "submittedMarketBid": False,
        "executedTeacherClearing": False,
        "note": (
            "The current public release contains matching frontend and "
            "backend research and manual-clearing route availability. "
            "This does not attest deployed "
            "Git SHA, teacher PMSS correctness or counterfactual performance."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify PowerBid public frontend lazy chunks + safe research API"
    )
    parser.add_argument(
        "--origin", default="https://power.smirel.com",
        help="Explicit PowerBid application origin (not the teacher PMSS URL)",
    )
    args = parser.parse_args(argv)
    try:
        report = inspect_powerbid_release(args.origin)
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError):
        print(json.dumps({
            "state": "DEPLOYMENT_PARITY_UNVERIFIED",
            "safeForMarketBidding": False,
            "note": "Public site check failed. No PMSS write or clearing attempted.",
        }, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
