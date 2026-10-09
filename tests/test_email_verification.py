"""Email confirmation regression tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import account_auth as auth  # noqa: E402
from app import email_verification as email_auth  # noqa: E402
from app.web_server import app  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("POWERBID_AUTH_ENABLED", "1")
    monkeypatch.setenv("POWERBID_REGISTRATION_OPEN", "1")
    monkeypatch.setenv("POWERBID_COOKIE_SECURE", "0")
    monkeypatch.setenv("POWERBID_AUTH_DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("POWERBID_EMAIL_VERIFICATION_ENABLED", "1")
    monkeypatch.setenv("POWERBID_EMAIL_FROM", "Example <sample@example.com>")
    monkeypatch.setenv("POWERBID_RESEND_API_KEY", "local-placeholder")
    monkeypatch.setenv("POWERBID_EMAIL_CODE_SECRET", "local-test-pepper-not-production")
    delivered = []

    async def fake_delivery(email, code):
        delivered.append((email, code))

    monkeypatch.setattr(email_auth, "_deliver", fake_delivery)
    with TestClient(app) as client:
        yield client, delivered


def test_issue_and_register(env):
    client, delivered = env
    headers = {"X-PowerBid-Request": "1"}
    address = "sample.register@example.com"
    payload = {
        "username": "sample_member_23",
        "email": address,
        "password": "TwelveOrMoreCharacters26",
    }
    assert client.get("/api/auth/config").json()["email_verification_enabled"] is True
    assert client.post("/api/auth/register", headers=headers, json=payload).status_code == 422
    send = client.post("/api/auth/email/send-code", headers=headers, json={"email": address})
    assert send.status_code == 200, send.text
    assert delivered[0][0] == address
    code = delivered[0][1]
    assert len(code) == 6
    assert (
        client.post(
            "/api/auth/email/send-code", headers=headers, json={"email": address}
        ).status_code
        == 429
    )
    wrong = "000000" if code != "000000" else "111111"
    assert (
        client.post(
            "/api/auth/register", headers=headers, json={**payload, "email_code": wrong}
        ).status_code
        == 403
    )
    created = client.post(
        "/api/auth/register", headers=headers, json={**payload, "email_code": code}
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "member"
    with auth.connection() as db:
        assert db.execute("SELECT count(*) FROM email_verification_codes").fetchone()[0] == 0
    assert (
        client.post(
            "/api/auth/register", headers=headers, json={**payload, "email_code": code}
        ).status_code
        != 201
    )


def test_no_mailing_if_email_in_use(env):
    client, delivered = env
    with auth.connection() as db:
        db.execute(
            "INSERT INTO users(username,email,password_hash,role,active,created_at)"
            "VALUES(?,?,?,'member',1,?)",
            ("existing_user", "existing@example.com", auth.HASHER.hash("examplePassword2026"), 1),
        )
    result = client.post(
        "/api/auth/email/send-code",
        headers={"X-PowerBid-Request": "1"},
        json={"email": "existing@example.com"},
    )
    assert result.status_code == 200
    assert delivered == []


def test_incomplete_mail_configuration_refuses_signup(env, monkeypatch):
    client, _ = env
    monkeypatch.delenv("POWERBID_RESEND_API_KEY")
    assert (
        client.post(
            "/api/auth/email/send-code",
            headers={"X-PowerBid-Request": "1"},
            json={"email": "a@example.com"},
        ).status_code
        == 503
    )
    assert (
        client.post(
            "/api/auth/register",
            headers={"X-PowerBid-Request": "1"},
            json={
                "username": "some_user",
                "email": "a@example.com",
                "password": "examplePassword2026",
                "email_code": "123456",
            },
        ).status_code
        == 503
    )
