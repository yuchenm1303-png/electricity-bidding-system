"""All external PMSS mutations here are FAKE, no school HTTP calls."""
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import pmss_live_api as live
from app.web_server import app
from powerbid.adapters.teacher_platform import (
    TeacherPlatformAdapter,
    TeacherPlatformAuthenticationExpired,
    TeacherPlatformContext,
)


class FakeSchool:
    def __init__(self):
        self.saves = 0
        self.clearings = 0
        self.saved = None
        self.expired = False
        self.have_costs = True

    def list_projects(self, **kwargs):
        if self.expired:
            raise TeacherPlatformAuthenticationExpired("expired")
        return [{"projectId": "real-1"}]

    def get_context(self, project):
        if self.expired:
            raise TeacherPlatformAuthenticationExpired("expired")
        assert project == "real-1"
        return TeacherPlatformContext(
            project={"projectId": project},
            cases=({"caseId": "case-1", "caseDate": "2025-09-03",
                    "tmSceneDateKey": "date-1"},),
            market_system={
                "spotList": [{
                    "marketAtomType": "DA", "unitPowerDeclareSegmentConstraint": 5,
                    "priceLowerConstraint": 0, "priceUpperConstraint": 1000,
                    "useSameBiddingCurve": 1,
                }],
                "scopes": [{
                    "tmSceneDateKey": "date-1",
                    "datas": [{"selfSort": "DA", "scopeId": "s-1"}],
                }],
            },
            units=({"key": "U1", "mvarate": 1000},),
        )

    validate_segments = staticmethod(TeacherPlatformAdapter.validate_segments)
    build_unit_bid_payload = staticmethod(TeacherPlatformAdapter.build_unit_bid_payload)

    def get_unit_bid(self, **kwargs):
        assert kwargs == {"scope_id": "s-1", "unit_id": "U1"}
        old = dict(self.saved or {})
        if self.have_costs:
            old.update({
                "minTechPowerCost": 11, "startCostHot": 12,
                "startCostWarm": 13, "startCostCold": 14,
            })
        return old

    def save_unit_bid(self, payload, *, commit=False):
        assert commit is True
        assert payload["startCostWarm"] == 13
        self.saves += 1
        self.saved = json.loads(json.dumps(payload))
        return {"saved": True}

    def run_clearing(self, *, case_id, comment, commit=False):
        assert commit is True
        assert case_id == "case-1"
        assert comment
        self.clearings += 1
        return {"started": True}

    def get_clearing_result(self, *, case_id, market_type_atom):
        assert case_id == "case-1" and market_type_atom == "DA"
        return {"isConverge": True, "iters": 5, "not_public": "secret"}

    def get_result_overview(self, *, case_id, market_type_atom):
        assert case_id == "case-1" and market_type_atom == "DA"
        return {"totalCost": 1234, "private": "secret"}


@pytest.fixture
def local(monkeypatch, tmp_path):
    monkeypatch.setenv("PMSS_LIVE_INTENTS_DB", str(tmp_path / "intents.sqlite3"))
    monkeypatch.setenv("PMSS_BASE_URL", "https://school.invalid")
    monkeypatch.setenv("PMSS_COOKIE_FILE", str(tmp_path / "cookies.json"))
    monkeypatch.setenv("PMSS_LIVE_PROJECT_MAP_FILE", str(tmp_path / "map.json"))
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text('{"test_session":"fake"}')
    cookie_file.chmod(0o600)
    map_file = tmp_path / "map.json"
    map_file.write_text('{"group2":"real-1"}')
    map_file.chmod(0o600)
    school = FakeSchool()
    monkeypatch.setattr(live, "_adapter", lambda: school)
    monkeypatch.setattr(live, "_remote_project_id", lambda _: "real-1")
    monkeypatch.setattr(live, "_catalog", lambda: (
        tmp_path, [{"project_id": "group2",
                    "cases": [{"case_date": "2025-09-03"}]}],
    ))
    identity = {"id": 1, "role": "admin"}
    monkeypatch.setattr(live, "require_user", lambda request, admin=False: identity)
    with TestClient(app) as client:
        yield client, school, identity


def _prepare(client):
    return client.post("/api/pmss/live/prepare", json={
        "project_id": "group2", "case_date": "2025-09-03",
        "target_unit_id": "U1", "segments": [
            {"start_power": 0, "end_power": 500, "price": 200},
            {"start_power": 500, "end_power": 1000, "price": 300},
        ],
    }, headers={"X-PowerBid-Request": "1"})


def _post(client, route, token, confirmation="核对"):
    return client.post("/api/pmss/live/" + route,
                       json={"intent_token": token, "confirmation": confirmation},
                       headers={"X-PowerBid-Request": "1"})


def test_live_original_handoff_requires_2_distinct_confirmations(local):
    client, school, _identity = local
    preview = _prepare(client)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    token = plan["intent_token"]
    assert len(token) >= 30 and plan["teacher_write_performed"] is False
    assert school.saves == school.clearings == 0
    assert _post(client, "submit", token, "wrong").status_code == 422
    assert _post(client, "execute", token, "执行出清 U1 2025-09-03").status_code == 409
    assert school.saves == school.clearings == 0
    submitted = _post(client, "submit", token, "提交报价 U1 2025-09-03")
    assert submitted.status_code == 200
    assert school.saves == 1
    assert _post(client, "submit", token, "提交报价 U1 2025-09-03").status_code == 409
    assert _post(client, "execute", token, "执行出清 U1 2025-09-03").status_code == 409
    checked = _post(client, "verify-saved", token)
    assert checked.status_code == 200
    assert checked.json()["readback_verified"] is True
    done = _post(client, "execute", token, "执行出清 U1 2025-09-03")
    assert done.status_code == 200, done.text
    assert school.saves == school.clearings == 1
    assert _post(client, "execute", token, "执行出清 U1 2025-09-03").status_code == 409
    result = client.get("/api/pmss/live/result", params={"intent_token": token})
    assert result.status_code == 200
    assert result.json()["school_clearing_status"] == {"isConverge": True, "iters": 5}
    assert result.json()["school_result_overview"] == {"totalCost": 1234}
    assert result.json()["candidate_causality_independently_verified"] is False
    assert school.saves == school.clearings == 1


def test_readback_mismatch_and_unknown_save_never_replay(local):
    client, school, _identity = local
    token = _prepare(client).json()["intent_token"]
    assert _post(client, "submit", token, "提交报价 U1 2025-09-03").status_code == 200
    school.saved["datas"][0]["segmentDatas"][0]["price"] = 999
    status = _post(client, "verify-saved", token)
    assert status.status_code == 200 and status.json()["readback_verified"] is False
    assert _post(client, "execute", token, "执行出清 U1 2025-09-03").status_code == 409
    assert school.clearings == 0


def test_bad_school_login_or_missing_costs_never_mutate(local):
    client, school, _identity = local
    school.expired = True
    assert _prepare(client).status_code == 409
    school.expired = False
    school.have_costs = False
    assert _prepare(client).status_code == 422
    assert school.saves == school.clearings == 0


def test_unapproved_other_user_cannot_reuse_intent(local):
    client, school, identity = local
    token = _prepare(client).json()["intent_token"]
    identity["id"] = 2
    assert _post(client, "submit", token, "提交报价 U1 2025-09-03").status_code == 404
    assert client.get("/api/pmss/live/result", params={"intent_token": token}).status_code == 404
    assert school.saves == school.clearings == 0


def test_local_store_is_persistent_and_one_time(local):
    client, _school, identity = local
    token = _prepare(client).json()["intent_token"]
    before = live._intent(token, identity["id"])
    assert before["state"] == "PREPARED"
    live._transition(token, identity["id"], ("PREPARED",), "SAVING")
    with pytest.raises(HTTPException, match="已执行或状态未确认"):
        live._transition(token, identity["id"], ("PREPARED",), "SAVING")
    assert live._intent(token, identity["id"])["state"] == "SAVING"
