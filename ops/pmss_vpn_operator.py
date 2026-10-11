"""Host-side, offline, fixed-purpose EasyConnect operator.

No network listener, shell execution, arbitrary Docker path, credential
storage, or PMSS platform writes. Only the PowerBid socket-mounted API
container can connect to this Unix-domain socket.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler

SOCKET_PATH = "/run/powerbid-operator/vpn.sock"
DOCKER_SOCKET = "/var/run/docker.sock"
CONTAINER = "powerbid-easyconnect"
COOLDOWN_SECONDS = 180
_guard = threading.Lock()
_last_restart = 0.0


class DockerLocal(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("docker", timeout=21)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(DOCKER_SOCKET)


def docker_call(method: str, path: str) -> tuple[int, dict]:
    # Only this module supplies the Docker paths, never HTTP clients.
    conn = DockerLocal()
    try:
        conn.request(method, path, headers={"Accept": "application/json"})
        result = conn.getresponse()
        raw = result.read(65536)
        data = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data = parsed
            except ValueError:
                pass
        return result.status, data
    finally:
        conn.close()


def running() -> bool:
    status, body = docker_call("GET", "/containers/" + CONTAINER + "/json")
    return status == 200 and body.get("State", {}).get("Running") is True


def reconnect() -> tuple[int, dict]:
    global _last_restart
    with _guard:
        elapsed = time.monotonic() - _last_restart
        if _last_restart > 0 and elapsed < COOLDOWN_SECONDS:
            return 429, {"code": "rate_limited"}
        _last_restart = time.monotonic()
        try:
            status, _ = docker_call(
                "POST", "/containers/" + CONTAINER + "/restart?t=15"
            )
        except (OSError, TimeoutError):
            return 503, {"code": "operator_unavailable"}
        if status != 204:
            return 503, {"code": "restart_failed"}
        return 200, {"restart_requested": True, "vpn_authenticated": False}


class Handler(BaseHTTPRequestHandler):
    server_version = "PowerBidVPNOperator"
    protocol_version = "HTTP/1.0"

    def log_message(self, format, *args):
        # Never log HTTP request data, auth, Docker inspect or environment.
        return

    def answer(self, code: int, value: dict):
        data = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/status":
            self.answer(404, {"code": "not_found"})
            return
        try:
            state = running()
            with _guard:
                remaining = max(
                    0, int(COOLDOWN_SECONDS - (time.monotonic() - _last_restart))
                ) if _last_restart else 0
            self.answer(200, {"running": state, "retry_after_seconds": remaining})
        except (OSError, RuntimeError, ValueError):
            self.answer(503, {"code": "docker_unavailable"})

    def do_POST(self):
        if self.path != "/reconnect" or self.headers.get("Content-Length", "0") != "0":
            self.answer(404, {"code": "not_found"})
            return
        code, result = reconnect()
        self.answer(code, result)


class ThreadedUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    directory = os.path.dirname(SOCKET_PATH)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    if os.path.lexists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    with ThreadedUnixServer(SOCKET_PATH, Handler) as server:
        os.chmod(SOCKET_PATH, 0o600)
        server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
