"""Read-only acceptance reporting contract."""
from datetime import date

import pytest
from fastapi import HTTPException

from app import pmss_live_api as live

def test_latest_acceptance_requires_admin(monkeypatch):
    def deny(request,admin=False):
        raise HTTPException(403, "Admin only")
    monkeypatch.setattr(live,"require_user",deny)
    with pytest.raises(HTTPException) as exc:
        live.latest_acceptance(None,"pmss-group-2",date(2025,9,3),"G31")
    assert exc.value.status_code==403

def test_latest_acceptance_rejects_invalid_identifiers(monkeypatch):
    monkeypatch.setattr(live,"require_user",lambda request,admin=False:{"id":1})
    with pytest.raises(HTTPException) as exc:
        live.latest_acceptance(None,"",date(2025,9,3),"G31")
    assert exc.value.status_code==422
