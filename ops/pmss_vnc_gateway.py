"""Local-only RFB/VNC bridge for the server's EasyConnect GUI.

This process never serves HTTP/TCP. It exposes exactly one Unix-domain socket,
which forwards bytes to 127.0.0.1:15901 on the same host. Authentication,
Origin checks, rate limits and access control live in the PowerBid API server.
"""
from __future__ import annotations

import os
import socket
import socketserver
import threading

SOCKET_PATH = "/run/powerbid-console/vnc.sock"
TARGET = ("127.0.0.1", 15901)
_MAX_CONNECTIONS = threading.BoundedSemaphore(2)


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        if not _MAX_CONNECTIONS.acquire(blocking=False):
            return
        try:
            try:
                upstream = socket.create_connection(TARGET, timeout=6)
            except OSError:
                return
            with upstream:
                self.request.settimeout(60)
                upstream.settimeout(60)
                done = threading.Event()

                def relay(reader: socket.socket, writer: socket.socket) -> None:
                    try:
                        while not done.is_set():
                            try:
                                data = reader.recv(65536)
                            except socket.timeout:
                                continue
                            if not data:
                                break
                            writer.sendall(data)
                    except OSError:
                        pass
                    finally:
                        done.set()
                        try:
                            writer.shutdown(socket.SHUT_WR)
                        except OSError:
                            pass

                upstream_to_client = threading.Thread(
                    target=relay, args=(upstream, self.request), daemon=True
                )
                upstream_to_client.start()
                relay(self.request, upstream)
                upstream_to_client.join(timeout=3)
        finally:
            _MAX_CONNECTIONS.release()


class LocalServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 3


def main() -> None:
    folder = os.path.dirname(SOCKET_PATH)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    if os.path.lexists(SOCKET_PATH):
        raise RuntimeError("Refusing to unlink existing console socket")
    with LocalServer(SOCKET_PATH, Handler) as server:
        os.chmod(SOCKET_PATH, 0o600)
        server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
