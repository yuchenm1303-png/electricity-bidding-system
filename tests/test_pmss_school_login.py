"""Use test credentials only. No school login requests are made."""
import sys
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import pmss_connection_api as target
from app.web_server import app

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pmss_browser_operator import _submit_school_login


def test_school_login_requires_admin(monkeypatch):
    def reject(_request, admin=False):
        raise HTTPException(status_code=403, detail="forbidden")
    monkeypatch.setattr(target, "require_user", reject)
    with TestClient(app) as client:
        response = client.post("/api/pmss/connection/browser/login",
            headers={"X-PowerBid-Request": "1"},
            json={"username": "demo", "password": "example"})
        assert response.status_code == 403


def test_school_login_requires_custom_header(monkeypatch):
    monkeypatch.setattr(target, "require_user", lambda request, admin=False: {"role": "admin"})
    with TestClient(app) as client:
        response = client.post("/api/pmss/connection/browser/login",
            json={"username": "demo", "password": "example"})
        assert response.status_code == 403


def test_school_login_only_submits_once_and_never_returns_password(monkeypatch):
    calls = []
    monkeypatch.setattr(target, "require_user", lambda request, admin=False: {"role": "admin"})
    def forward(method, action, payload=None):
        calls.append((method, action, payload))
        return (200, b'{"submitted":true}')
    monkeypatch.setattr(target, "_browser_call", forward)
    with TestClient(app) as client:
        response = client.post("/api/pmss/connection/browser/login",
            headers={"X-PowerBid-Request":"1"},
            json={"username":"example_user","password":"not_a_real_password"})
        assert response.status_code == 200
        assert response.json() == {"submitted": True, "authenticated": False}
        assert len(calls) == 1 and calls[0][0:2] == ("POST", "login")
        assert "not_a_real_password" not in response.text


def test_school_login_does_not_claim_school_authentication(monkeypatch):
    monkeypatch.setattr(target, "require_user", lambda request, admin=False: {"role": "admin"})
    monkeypatch.setattr(target, "_browser_call",
                        lambda method, action, payload=None: (503, b'{}'))
    with TestClient(app) as client:
        r=client.post("/api/pmss/connection/browser/login",
                      headers={"X-PowerBid-Request":"1"},
                      json={"username":"demo","password":"example"})
        assert r.status_code == 503


def test_browser_operator_submits_only_on_login_site():
    class FakeDriver:
        current_url = "http://cq.university.netts-dev.tsintergy.com/"
        def __init__(self):
            self.events=[]
        def execute_script(self, js, *args):
            self.events.append(("script", len(args)))
            if "return Boolean" in js:
                return True
        def execute_cdp_cmd(self, name, payload):
            self.events.append((name, payload["text"][:1]))
    d=FakeDriver()
    _submit_school_login(d, "test", "temporary")
    assert sum(1 for name,_ in d.events if name=="Input.insertText") == 2
    d.current_url="http://cq.university.netts-dev.tsintergy.com/pmss/main.html"
    try:
        _submit_school_login(d,"test","temporary")
        raise AssertionError("school market page must never submit credentials")
    except ValueError:
        pass
