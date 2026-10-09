"""Security and functionality smoke tests for the isolated PowerBid account service."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Match the repository's existing API tests: CI runs pytest with only src on PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import account_auth  # noqa: E402
from app.web_server import app  # noqa: E402

HEADERS = {"X-PowerBid-Request": "1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("POWERBID_AUTH_ENABLED", "1")
    monkeypatch.setenv("POWERBID_REGISTRATION_OPEN", "1")
    monkeypatch.setenv("POWERBID_COOKIE_SECURE", "0")
    monkeypatch.setenv("POWERBID_AUTH_DB_PATH", str(tmp_path / "accounts" / "users.sqlite3"))
    with TestClient(app) as api:
        yield api


def register(client, name="tester01", email="tester@example.com"):
    return client.post(
        "/api/auth/register",
        headers=HEADERS,
        json={"username": name, "email": email, "password": "Good-Passphrase-2026"},
    )


def test_register_login_me_and_logout(client, tmp_path):
    assert client.get("/api/auth/config").json() == {
        "enabled": True,
        "registration_open": True,
    }
    assert client.get("/api/scenario").status_code == 401
    assert client.post("/api/optimize", json={}).status_code == 403
    assert client.get("/api/pmss/network-rank").status_code == 401
    reg = register(client)
    assert reg.status_code == 201, reg.text
    assert reg.json()["role"] == "member"
    assert "password_hash" not in reg.json()
    assert "httponly" in reg.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json()["username"] == "tester01"
    assert client.get("/api/scenario").status_code == 200
    assert client.post("/api/auth/logout", headers=HEADERS).json() == {"ok": True}
    assert client.get("/api/auth/me").status_code == 401
    fail = client.post(
        "/api/auth/login",
        headers=HEADERS,
        json={"username": "tester01", "password": "bad-password-123"},
    )
    assert fail.status_code == 401
    good = client.post(
        "/api/auth/login",
        headers=HEADERS,
        json={"username": "tester01", "password": "Good-Passphrase-2026"},
    )
    assert good.status_code == 200
    assert good.json()["username"] == "tester01"
    path = tmp_path / "accounts" / "users.sqlite3"
    assert path.exists()
    assert (path.stat().st_mode & 0o777) == 0o600
    with sqlite3.connect(str(path)) as db:
        assert db.execute("SELECT password_hash FROM users").fetchone()[0].startswith("$argon2id$")
        assert len(db.execute("SELECT token_hash FROM sessions").fetchone()[0]) == 64


def test_registration_validation_and_duplicate(client):
    assert register(client).status_code == 201
    assert register(client).status_code == 409
    bad = client.post(
        "/api/auth/register",
        headers=HEADERS,
        json={
            "username": "a-",
            "email": "bad-email",
            "password": "Good-Passphrase-2026",
        },
    )
    assert bad.status_code == 422
    assert (
        client.post(
            "/api/auth/register",
            json={
                "username": "other42",
                "email": "other@example.com",
                "password": "Good-Passphrase-2026",
            },
        ).status_code
        == 403
    )


def test_disabled_registration_and_csrf(client, monkeypatch):
    monkeypatch.setenv("POWERBID_REGISTRATION_OPEN", "0")
    assert register(client).status_code == 403
    assert (
        client.post(
            "/api/auth/login",
            headers={**HEADERS, "Origin": "https://malicious.example"},
            json={
                "username": "tester01",
                "password": "Good-Passphrase-2026",
            },
        ).status_code
        == 403
    )


def test_admin_can_disable_user_and_revoke_sessions(client):
    assert register(client).status_code == 201
    normal_cookie = client.cookies.get(account_auth.COOKIE)
    assert normal_cookie
    assert client.get("/api/auth/users").status_code == 403
    # Offline provisioning is the only route to administrator role.
    with account_auth.connection() as db:
        db.execute(
            (
                "INSERT INTO users(username,email,password_hash,role,active,created_at) "
                "VALUES(?,?,?,'admin',1,?)"
            ),
            ("owner01", "owner@example.com", account_auth.HASHER.hash("Owner-Passphrase-2026"), 1),
        )
    admin_client = TestClient(app)
    assert (
        admin_client.post(
            "/api/auth/login",
            headers=HEADERS,
            json={
                "username": "owner01",
                "password": "Owner-Passphrase-2026",
            },
        ).status_code
        == 200
    )
    users = admin_client.get("/api/auth/users").json()
    assert len(users) == 2
    uid = next(item["id"] for item in users if item["username"] == "tester01")
    result = admin_client.post(
        "/api/auth/users/" + str(uid) + "/enabled", headers=HEADERS, json={"enabled": False}
    )
    assert result.status_code == 200, result.text
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/scenario").status_code == 401
    assert admin_client.get("/api/auth/me").status_code == 200
    assert (
        admin_client.post(
            "/api/auth/users/2/enabled", headers=HEADERS, json={"enabled": False}
        ).status_code
        == 400
    )
    assert (
        admin_client.post(
            "/api/auth/users/" + str(uid) + "/enabled", headers=HEADERS, json={"enabled": True}
        ).status_code
        == 200
    )
    assert client.get("/api/auth/me").status_code == 401


def test_failed_login_rate_limited(client):
    assert register(client).status_code == 201
    client.post("/api/auth/logout", headers=HEADERS)
    wrong = {"username": "tester01", "password": "incorrectpass-999"}
    for _i in range(5):
        assert client.post("/api/auth/login", headers=HEADERS, json=wrong).status_code == 401
    locked = client.post(
        "/api/auth/login",
        headers=HEADERS,
        json={
            "username": "tester01",
            "password": "Good-Passphrase-2026",
        },
    )
    assert locked.status_code == 429


def test_opt_in_auth_preserves_original_demo(monkeypatch):
    monkeypatch.setenv("POWERBID_AUTH_ENABLED", "0")
    with TestClient(app) as anon:
        assert anon.get("/api/scenario").status_code == 200
        assert anon.get("/api/auth/config").json()["enabled"] is False
