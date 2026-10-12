"""Host-side restricted browser-login service; reuses the EXISTING school Chrome.

Run only on the Docker bridge gateway. Not a VNC server, generic proxy or
school bid writer. The main PowerBid backend authenticates administrators and
forwards commands using a local, owner-only shared token.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import requests
from pmss_browser_operator import handle_school_browser

_HOST = "172.17.0.1"
_PORT = 18761
_SCHOOL_READONLY_BRIDGE = (
    "http://172.17.0.1:18760/pmss/web/project/list"
    "?permissionType=0&projectType=1&pageSize=1&pageNo=1&version=base"
)


def _school_authorized():
    try:
        # A T200 response is the only authority; VPN status and cookie count
        # do not establish valid application authentication.
        result = requests.get(_SCHOOL_READONLY_BRIDGE, timeout=9, allow_redirects=False)
        if result.status_code != 200:
            raise RuntimeError("School API did not return a successful HTTP response")
        code = result.json().get("retCode")
        if code == "T200":
            return True
        if code == "T000":
            return False
        raise RuntimeError("Ambiguous school authentication status")
    except (requests.RequestException, ValueError, AttributeError):
        # Fail closed: a network error is not permission to interact with a
        # possibly authenticated PMSS administrator session.
        raise RuntimeError("School authentication cannot be determined")


class Handler(BaseHTTPRequestHandler):
    server_version = "PowerBidSchoolLogin/1.0"

    def log_message(self, fmt, *args):
        # Suppress all request metadata: even paths, timestamps and keyboard
        # actions should not become an accidental credentials audit trail.
        return

    def _json(self, status, value):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not handle_school_browser(self, urlsplit(self.path).path, _school_authorized):
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        if not handle_school_browser(self, urlsplit(self.path).path, _school_authorized):
            self._json(404, {"error": "not_found"})


if __name__ == "__main__":
    # Fixed, non-public Docker gateway interface, not 0.0.0.0 and not
    # exposed by any published container port / Caddy route.
    ThreadingHTTPServer((_HOST, _PORT), Handler).serve_forever()
