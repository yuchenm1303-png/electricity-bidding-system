"""Existing teacher-clearing attempts must be visible without another PMSS write."""
from datetime import date

import pytest
from fastapi import HTTPException

from app import pmss_live_api as live


def test_admin_can_recover_local_completed_attempt(monkeypatch, tmp_path):
    monkeypatch.setenv("PMSS_LIVE_INTENTS_DB", str(tmp_path / "attempts.sqlite3"))
    monkeypatch.setattr(live, "require_user", lambda request, admin=False: {"id": 3})
    with live._database() as db:
        db.execute(
            "INSERT INTO intents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("test-hash", 3, 1790000000, "CLEARING_REQUESTED",
             "pmss-group-2", "2025-09-03", "G31", "case-1", "{}"),
        )
    found = live.attempt_state(
        None, "pmss-group-2", date(2025, 9, 3), "G31"
    )
    assert found == {
        "exists": True,
        "state": "CLEARING_REQUESTED",
        "read_only": True,
        "school_write_performed": False,
    }
    other = live.attempt_state(
        None, "pmss-group-2", date(2025, 9, 3), "G32"
    )
    assert other["exists"] is False


def test_attempt_state_requires_admin(monkeypatch):
    def deny(request, admin=False):
        raise HTTPException(403, "admin required")
    monkeypatch.setattr(live, "require_user", deny)
    with pytest.raises(HTTPException) as exc:
        live.attempt_state(None, "pmss-group-2", date(2025, 9, 3), "G31")
    assert exc.value.status_code == 403
