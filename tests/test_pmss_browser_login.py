"""Tests use fake browser transport; never contact the school or send credentials."""
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import pmss_connection_api as target
from app.web_server import app


def test_school_browser_is_admin_only(monkeypatch):
    monkeypatch.setattr(target, "require_user", lambda request, admin=False:
        (_ for _ in ()).throw(HTTPException(403, "admin required")))
    with TestClient(app) as client:
        for endpoint in ("availability", "frame"):
            assert client.get("/api/pmss/connection/browser/" + endpoint).status_code == 403
        assert client.post("/api/pmss/connection/browser/action",
                           headers={"X-PowerBid-Request": "1"},
                           json={"action": "open"}).status_code == 403


def test_school_browser_fixed_transport_and_validation(monkeypatch):
    seen = []
    monkeypatch.setattr(target, "require_user",
                        lambda request, admin=False: {"id": 1, "role": "admin"})
    def forward(method, action, payload=None):
        seen.append((method, action, payload))
        if action == "status":
            return 200, b'{"ready":true}'
        if action == "frame":
            return 200, bytes((137, 80, 78, 71, 13, 10, 26, 10)) + b"fake"
        return 200, b'{"ok":true}'
    monkeypatch.setattr(target, "_browser_call", forward)
    with TestClient(app) as client:
        assert client.get("/api/pmss/connection/browser/availability").json() == {
            "available": True
        }
        frame = client.get("/api/pmss/connection/browser/frame")
        assert frame.status_code == 200
        assert frame.headers["cache-control"] == "private, no-store"
        assert frame.headers["content-type"] == "image/png"
        assert client.post("/api/pmss/connection/browser/action",
                           headers={"X-PowerBid-Request": "1"},
                           json={"action": "open"}).json() == {"ok": True}
        assert client.post("/api/pmss/connection/browser/action",
                           headers={"X-PowerBid-Request": "1"},
                           json={"action": "text", "text": "pw\n"}).status_code == 422
        assert client.post("/api/pmss/connection/browser/action",
                           headers={"X-PowerBid-Request": "1"},
                           json={"action": "click", "x": 5000, "y": 7}).status_code == 422
        assert client.post("/api/pmss/connection/browser/action",
                           json={"action": "open"}).status_code == 200  # no auth middleware when disabled
    assert seen[:3] == [
        ("GET", "status", None), ("GET", "frame", None),
        ("POST", "action", {"action": "open"}),
    ]
    assert not any(v and v.get("text") for _, _, v in seen)


def test_school_browser_stops_after_auth(monkeypatch):
    monkeypatch.setattr(target, "require_user",
                        lambda request, admin=False: {"id": 1, "role": "admin"})
    monkeypatch.setattr(target, "_browser_call",
                        lambda method, action, payload=None: (409, b'{}'))
    with TestClient(app) as client:
        response = client.post("/api/pmss/connection/browser/action",
                               headers={"X-PowerBid-Request": "1"},
                               json={"action": "click", "x": 10, "y": 40})
        assert response.status_code == 409
        assert client.get("/api/pmss/connection/browser/availability").json() == {
            "available": False
        }
