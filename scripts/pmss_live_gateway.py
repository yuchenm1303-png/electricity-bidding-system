"""Original PMSS bridge with *two* explicitly authorized market-write routes.

Runs in the existing authenticated school server browser's host context.
All established read-only paths continue using the existing bridge module,
which owns the VPN proxy and in-memory authenticated school session.

No school cookies leave the bridge. The only writable upstream endpoints
are the teacher's original five-segment bid save and clearing execute.
"""
from __future__ import annotations

import hmac
import json
import math
import stat
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import bridge

_WRITE_TOKEN_PATH = "/srv/powerbid-platform/private-cases/.pmss-live-write-token"
_WRITE_PATHS = {
    "/pmss/web/tmScene/spot/unit/electricEnergy",
    "/pmss/web/simulate/execute",
}
_SESSION_LOCK = threading.RLock()


def _valid_secret(supplied: str) -> bool:
    try:
        path = Path(_WRITE_TOKEN_PATH)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            return False
        expected = path.read_text("ascii").strip()
        return len(expected) >= 40 and hmac.compare_digest(expected, supplied)
    except (OSError, ValueError):
        return False


def _valid_bid(data: object) -> bool:
    if not isinstance(data, dict) or set(data) != {
        "scopeId", "unitId", "datas", "minTechPowerCost",
        "startCostHot", "startCostWarm", "startCostCold"
    }:
        return False
    if not all(isinstance(data.get(k), str) and 1 <= len(data[k]) <= 128
               for k in ("scopeId", "unitId")):
        return False
    if any(not isinstance(data.get(k), (int, float)) or
           not math.isfinite(data[k]) for k in
           ("minTechPowerCost", "startCostHot", "startCostWarm", "startCostCold")):
        return False
    periods = data.get("datas")
    if not isinstance(periods, list) or len(periods) != 1:
        return False
    period = periods[0]
    if not isinstance(period, dict) or set(period) != {
        "startPeriod", "endPeriod", "segmentDatas"
    } or period["startPeriod"] != 1 or period["endPeriod"] != 24:
        return False
    segments = period["segmentDatas"]
    if not isinstance(segments, list) or len(segments) != 5:
        return False
    for index, segment in enumerate(segments, 1):
        if not isinstance(segment, dict) or set(segment) != {
            "startPower", "endPower", "price", "segmentOrder"
        } or segment["segmentOrder"] != index:
            return False
        if any(isinstance(segment[k], bool) or
               not isinstance(segment[k], (float, int)) or
               not math.isfinite(segment[k]) for k in
               ("startPower", "endPower", "price")):
            return False
        if not (0 <= segment["startPower"] < segment["endPower"] <= 20000
                and 0 <= segment["price"] <= 1000):
            return False
        if index > 1 and abs(segment["startPower"] -
                             segments[index - 2]["endPower"]) > 1e-6:
            return False
    return True


def _valid_clearing(data: object) -> bool:
    return (isinstance(data, dict)
            and set(data) == {"caseId", "comment"}
            and isinstance(data["caseId"], str)
            and 1 <= len(data["caseId"]) <= 128
            and isinstance(data["comment"], str)
            and len(data["comment"]) <= 500)


class SecureBridgeHandler(bridge.Handler):
    """Use existing live PMSS session; no new remote login or cookie export."""

    def _handle(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/_powerbid/write-gate-ready":
            if (self.command != "GET" or parsed.query or
                    not _valid_secret(self.headers.get("X-PowerBid-Write-Gate", ""))):
                self._json(403, {"ok": False, "error": "write_not_authorized"})
                return
            self._json(200, {"ready": True, "source": "ORIGINAL_PMSS_RESTRICTED"})
            return
        if parsed.path not in _WRITE_PATHS or self.command != "POST":
            with _SESSION_LOCK:
                return super()._handle()
        # Token check takes place BEFORE accessing any request body.
        if parsed.query or not _valid_secret(
            self.headers.get("X-PowerBid-Write-Gate", "")
        ):
            self._json(403, {"ok": False, "error": "write_not_authorized"})
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._json(415, {"ok": False, "error": "json_required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 2 <= length <= 32768:
                raise ValueError("invalid_content_length")
            body = self.rfile.read(length)
            data = json.loads(body)
        except (ValueError, TypeError, OverflowError):
            self._json(422, {"ok": False, "error": "invalid_body"})
            return
        valid = (_valid_bid(data)
                 if parsed.path.endswith("/electricEnergy")
                 else _valid_clearing(data))
        if not valid:
            self._json(422, {"ok": False, "error": "invalid_pmss_payload"})
            return

        with _SESSION_LOCK:
            try:
                # Verify school T200 via GET first; safe login renewal only
                # occurs BEFORE irreversible POST, never after it.
                probe = bridge.upstream_request(
                    "GET", "/pmss/web/project/list",
                    "permissionType=0&projectType=1&pageSize=1&pageNo=1&version=base",
                    None,
                )
                if probe.status_code != 200 or probe.json().get("retCode") != "T200":
                    self._json(409, {"ok": False, "error": "school_login_required"})
                    return
                # One single school POST. Do not retry even for T000,
                # an ambiguous timeout, or connection break.
                upstream = bridge.session.request(
                    "POST", bridge.UPSTREAM + parsed.path,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                    allow_redirects=False,
                )
                if not (200 <= upstream.status_code < 300):
                    self._json(502, {"ok": False, "error": "school_post_unverified"})
                    return
                try:
                    payload = upstream.json()
                except ValueError:
                    self._json(502, {"ok": False, "error": "school_post_non_json"})
                    return
                if (not isinstance(payload, dict)
                        or payload.get("retCode") != "T200"):
                    self._json(502, {"ok": False, "error": "school_post_not_acknowledged"})
                    return
                self._json(200, {"retCode": "T200", "data": payload.get("data")})
            except Exception:
                # Never disclose remote URLs, cookies, fields or response text.
                self._json(502, {"ok": False, "error": "school_post_uncertain"})
            return


def main():
    bridge.refresh_cookies()
    server = ThreadingHTTPServer((bridge.BIND, bridge.PORT), SecureBridgeHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
