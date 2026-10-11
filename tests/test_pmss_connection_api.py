"""Admin-only PMSS connection controls and fixed-scope VPN operator."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import account_auth, pmss_connection_api  # noqa: E402
from app.web_server import app  # noqa: E402


@pytest.fixture
def clients(monkeypatch, tmp_path):
    monkeypatch.setenv("POWERBID_AUTH_ENABLED", "1")
    monkeypatch.setenv("POWERBID_COOKIE_SECURE", "0")
    monkeypatch.setenv("POWERBID_REGISTRATION_OPEN", "1")
    monkeypatch.setenv("POWERBID_AUTH_DB_PATH", str(tmp_path / "accounts.sqlite"))
    with account_auth.connection() as db:
        for username, role in [("pmssmember", "member"), ("pmssadmin", "admin")]:
            db.execute(
                "INSERT INTO users(username,email,password_hash,role,active,created_at)"
                " VALUES(?,?,?,?,1,1)",
                (username, username + "@example.com",
                 account_auth.HASHER.hash("Test-vpn-passphrase-2026"), role),
            )
    def logged(name):
        client = TestClient(app)
        r = client.post(
            "/api/auth/login",
            json={"username": name, "password": "Test-vpn-passphrase-2026"},
            headers={"X-PowerBid-Request": "1"},
        )
        assert r.status_code == 200
        return client
    return logged


def test_guest_blocked_but_member_can_read_shared_status(clients, monkeypatch):
    calls = []

    def operator(method, path):
        calls.append((method, path))
        return {"running": True, "retry_after_seconds": 0}

    monkeypatch.setattr(pmss_connection_api, "_operator", operator)
    monkeypatch.setattr(pmss_connection_api, "_probe_bridge", lambda: "unreachable")
    with TestClient(app) as guest:
        assert guest.get("/api/pmss/connection/status").status_code == 401
        assert guest.post(
            "/api/pmss/connection/reconnect",
            headers={"X-PowerBid-Request": "1"},
        ).status_code == 401

    with clients("pmssmember") as member:
        result = member.get("/api/pmss/connection/status")
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["operator"] == "ready"
        assert body["shared_connection"] is True
        assert body["reconnect_allowed"] is True
        assert body["pmss_access"] == "unreachable"
    assert calls == [("GET", "/status")]


def test_member_can_reconnect_only_during_confirmed_outage(clients, monkeypatch):
    calls = []

    def fake(method, path):
        calls.append((method, path))
        return {"restart_requested": True}

    monkeypatch.setattr(pmss_connection_api, "_operator", fake)
    monkeypatch.setattr(pmss_connection_api, "_probe_bridge", lambda: "unreachable")
    with clients("pmssmember") as member:
        assert member.post("/api/pmss/connection/reconnect").status_code == 403
        assert member.post(
            "/api/pmss/connection/reconnect",
            json={"container": "termrelay-postgres", "command": "stop"},
            headers={"X-PowerBid-Request": "1"},
        ).status_code == 422
        assert calls == []
        response = member.post(
            "/api/pmss/connection/reconnect",
            headers={"X-PowerBid-Request": "1"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["vpn_authenticated"] is False
    assert calls == [("POST", "/reconnect")]


@pytest.mark.parametrize(
    ("probe", "code"),
    [
        ("authorized", 409),
        ("login_required", 409),
        ("unknown", 503),
    ],
)
def test_member_cannot_interrupt_non_outage(clients, monkeypatch, probe, code):
    calls = []
    def operator(method, path):
        calls.append((method, path))
        return {"running": True, "retry_after_seconds": 0}

    monkeypatch.setattr(pmss_connection_api, "_operator", operator)
    monkeypatch.setattr(pmss_connection_api, "_probe_bridge", lambda: probe)
    with clients("pmssmember") as member:
        state = member.get("/api/pmss/connection/status").json()
        assert state["pmss_access"] == probe
        assert state["reconnect_allowed"] is False
        result = member.post(
            "/api/pmss/connection/reconnect",
            headers={"X-PowerBid-Request": "1"},
        )
        assert result.status_code == code
    assert calls == [("GET", "/status")]


def test_admin_status_has_no_credentials_and_exact_state(clients, monkeypatch):
    monkeypatch.setattr(
        pmss_connection_api, "_operator",
        lambda method, path: {
            "running": True,
            "retry_after_seconds": 76,
            "cookie": "MUST_NOT_LEAK",
        },
    )
    monkeypatch.setattr(pmss_connection_api, "_probe_bridge", lambda: "login_required")
    with clients("pmssadmin") as admin:
        response = admin.get("/api/pmss/connection/status")
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["operator"] == "ready"
        assert state["vpn_container"] == "running"
        assert state["pmss_access"] == "login_required"
        assert state["reconnect_allowed"] is False
        assert state["retry_after_seconds"] == 76
        assert state["external_login_is_server_session"] is False
        assert state["writes_to_teacher_platform"] is False
        assert response.headers["cache-control"].startswith("private, no-store")
        assert "MUST_NOT_LEAK" not in response.text
        assert not any(
            sensitive in response.text.lower()
            for sensitive in ("password", "cookie", "session_token")
        )


def test_reconnect_fail_closed_and_cooldown(clients, monkeypatch):
    monkeypatch.setattr(pmss_connection_api, "_probe_bridge", lambda: "unreachable")

    def offline(*_args):
        raise OSError("server secret must not leak")

    monkeypatch.setattr(pmss_connection_api, "_operator", offline)
    with clients("pmssmember") as member:
        result = member.post(
            "/api/pmss/connection/reconnect",
            headers={"X-PowerBid-Request": "1"},
        )
        assert result.status_code == 503
        assert "server secret" not in result.text
        status = member.get("/api/pmss/connection/status")
        assert status.json()["operator"] == "unavailable"
        monkeypatch.setattr(
            pmss_connection_api, "_operator",
            lambda *args: (_ for _ in ()).throw(RuntimeError("rate_limited")),
        )
        limited = member.post(
            "/api/pmss/connection/reconnect",
            headers={"X-PowerBid-Request": "1"},
        )
        assert limited.status_code == 429


def test_probe_unexpected_response_cannot_claim_outage(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, length):
            return b'{"retCode":"T999"}'

    monkeypatch.setattr(pmss_connection_api, "urlopen", lambda *args, **kwargs: Response())
    monkeypatch.setattr(pmss_connection_api, "_PROBE_CACHE", (0.0, "unknown"))
    assert pmss_connection_api._probe_bridge() == "unknown"


def test_host_operator_uses_only_fixed_docker_paths(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "fixed_operator", Path(__file__).resolve().parents[1] / "ops/pmss_vpn_operator.py"
    )
    assert spec is not None and spec.loader is not None
    operator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(operator)
    calls = []
    def fake(method, path):
        calls.append((method, path))
        if method == "GET":
            return 200, {"State": {"Running": True}, "Config": {"Env": ["PASSWORD=private"]}}
        return 204, {}
    monkeypatch.setattr(operator, "docker_call", fake)
    assert operator.running() is True
    code, result = operator.reconnect()
    assert code == 200 and result["restart_requested"] is True
    assert result["vpn_authenticated"] is False
    second, _ = operator.reconnect()
    assert second == 429
    assert calls == [
        ("GET", "/containers/powerbid-easyconnect/json"),
        ("POST", "/containers/powerbid-easyconnect/restart?t=15"),
    ]
