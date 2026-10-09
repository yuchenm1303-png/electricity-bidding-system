"""OAuth state, identity collision, and Turnstile server enforcement tests."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import account_auth as auth  # noqa: E402
from app import social_auth, turnstile_auth  # noqa: E402
from app.web_server import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("POWERBID_AUTH_ENABLED", "1")
    monkeypatch.setenv("POWERBID_REGISTRATION_OPEN", "1")
    monkeypatch.setenv("POWERBID_COOKIE_SECURE", "0")
    monkeypatch.setenv("POWERBID_AUTH_DB_PATH", str(tmp_path / "accounts.sqlite3"))
    monkeypatch.delenv("POWERBID_TURNSTILE_SITE_KEY", raising=False)
    monkeypatch.delenv("POWERBID_TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("POWERBID_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("POWERBID_GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("POWERBID_GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("POWERBID_GITHUB_CLIENT_SECRET", raising=False)
    with TestClient(app) as c:
        yield c


def test_social_off_by_default(client):
    assert client.get("/api/auth/config").json()["social"] == {
        "google": False,
        "github": False,
    }
    assert client.get("/api/auth/oauth/google/start").status_code == 503
    assert client.get("/api/auth/oauth/github/start").status_code == 503


def test_oauth_browser_state_is_single_use(client, monkeypatch):
    monkeypatch.setenv("POWERBID_GOOGLE_CLIENT_ID", "test-google-id")
    monkeypatch.setenv("POWERBID_GOOGLE_CLIENT_SECRET", "test-google-secret")

    async def fake_identity(provider, code):
        assert provider == "google" and code == "fake-auth-code"
        return "subject-unique-501", "unique501@example.test"

    monkeypatch.setattr(social_auth, "fetch_identity", fake_identity)
    response = client.get("/api/auth/oauth/google/start", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://accounts.google.com/")
    state = client.cookies.get("pb_oauth_google")
    assert state and len(state) > 30
    assert state in response.headers["location"]
    invalid = client.get(
        "/api/auth/oauth/google/callback?state=wrong&code=fake-auth-code",
        follow_redirects=False,
    )
    assert invalid.status_code == 303
    assert "/login?" in invalid.headers["location"]
    # The rejected callback clears this browser's state cookie.
    client.cookies.set("pb_oauth_google", state, path="/api/auth/oauth/google/callback")
    result = client.get(
        f"/api/auth/oauth/google/callback?state={state}&code=fake-auth-code",
        follow_redirects=False,
    )
    assert result.status_code == 303
    assert result.headers["location"] == "/app"
    assert client.get("/api/auth/me").json()["role"] == "member"
    with auth.connection() as db:
        stored = db.execute("SELECT digest FROM oauth_states").fetchone()
        assert stored is None
        linked = db.execute("SELECT provider,subject FROM oauth_identities").fetchone()
        assert linked["provider"] == "google"
    replay = client.get(
        f"/api/auth/oauth/google/callback?state={state}&code=fake-auth-code",
        follow_redirects=False,
    )
    assert replay.headers["location"].startswith("/login?auth_error=")


def test_social_never_steals_an_existing_email(client):
    auth.HASHER.hash("setup")  # ensure hashing is available
    with auth.connection() as db:
        db.execute(
            "INSERT INTO users(username,email,password_hash,role,active,created_at) "
            "VALUES(?,?,?,'admin',1,?)",
            (
                "adminuser",
                "exists@example.test",
                auth.HASHER.hash("admin-password-2026!"),
                int(time.time()),
            ),
        )
    with pytest.raises(FileExistsError):
        social_auth.resolve_user("github", "gh-101", "exists@example.test")
    with auth.connection() as db:
        assert db.execute("SELECT count(*) FROM oauth_identities").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_turnstile_misconfiguration_fails_closed(client, monkeypatch):
    monkeypatch.setenv("POWERBID_TURNSTILE_SITE_KEY", "dummy-site")
    payload = {
        "username": "example501",
        "email": "example501@test.com",
        "password": "strong-password-2026",
        "turnstile_token": "x",
    }
    assert (
        client.post(
            "/api/auth/register", json=payload, headers={"X-PowerBid-Request": "1"}
        ).status_code
        == 503
    )


def test_turnstile_rejects_missing_token(client, monkeypatch):
    monkeypatch.setenv("POWERBID_TURNSTILE_SITE_KEY", "dummy-site")
    monkeypatch.setenv("POWERBID_TURNSTILE_SECRET_KEY", "dummy-secret")
    response = client.post(
        "/api/auth/register",
        json={
            "username": "example502",
            "email": "example502@test.com",
            "password": "strong-password-2026",
        },
        headers={"X-PowerBid-Request": "1"},
    )
    assert response.status_code == 422
    assert client.get("/api/auth/config").json()["turnstile_site_key"] == "dummy-site"


def test_turnstile_server_verifies_hostname(client, monkeypatch):
    monkeypatch.setenv("POWERBID_TURNSTILE_SITE_KEY", "sitekey")
    monkeypatch.setenv("POWERBID_TURNSTILE_SECRET_KEY", "secretkey")
    monkeypatch.setenv("POWERBID_TURNSTILE_HOSTNAME", "power.smirel.com")

    class FakeResponse:
        def __init__(self, host):
            self.host = host

        def raise_for_status(self):
            pass

        def json(self):
            return {"success": True, "hostname": self.host}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, data):
            assert url == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
            assert data["secret"] == "secretkey" and data["response"] == "valid-token"
            return FakeResponse("wrong.example")

    monkeypatch.setattr(turnstile_auth.httpx, "AsyncClient", FakeClient)
    response = client.post(
        "/api/auth/register",
        json={
            "username": "example503",
            "email": "example503@test.com",
            "password": "strong-password-2026",
            "turnstile_token": "valid-token",
        },
        headers={"X-PowerBid-Request": "1"},
    )
    assert response.status_code == 403
    with auth.connection() as db:
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 0
