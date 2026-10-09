"""Synthetic manual PMSS observed-result flow, never teacher platform writes."""
from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_pmss_web_api import safe_snapshot

from app.web_server import app


def payload():
    old = safe_snapshot()
    observed = deepcopy(old["results"])
    observed["unitResults"][0]["power"]["datas"] = [70]*24
    observed["unitResults"][0]["income"]["datas"] = [7000]*24
    return {
        "snapshot": old, "target_unit_id": "G30",
        "recommended_segments": [
            {"start_power": i*20, "end_power": (i+1)*20, "price": 60+i*5}
            for i in range(5)
        ],
        "result_case_date": "2025-09-01",
        "observed_results": observed, "operator_confirmed": True,
    }


def test_import_matches_original_case_and_preserves_research_only_labels():
    result = TestClient(app).post("/api/pmss/manual-clearing-review", json=payload())
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["observed_accepted_mwh"] == pytest.approx(1680)
    assert body["reported_income_sum"] == pytest.approx(168000)
    assert body["periods"] == 24
    assert len(body["hours"]) == 24
    assert body["association"] == "OPERATOR_ASSERTED_ONLY"
    for key in ("teacher_result_authenticated", "candidate_bid_causality_verified",
                "reported_income_is_net_profit", "pmss_write_performed",
                "pmss_clearing_executed", "automatic_submission_enabled"):
        assert body[key] is False


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(operator_confirmed=False),
    lambda p: p.update(result_case_date="2025-09-02"),
    lambda p: p.update(target_unit_id="G31"),
    lambda p: p.update(observed_results=deepcopy(p["snapshot"]["results"])),
    lambda p: p["observed_results"].update(marketTypeAtom="RT"),
    lambda p: p["observed_results"].update(periodNum=23),
    lambda p: p["observed_results"]["unitResults"][0]["power"].update(datas=[70]*23),
    lambda p: p["observed_results"]["unitResults"][0]["power"].update(datas=[1000]*24),
    lambda p: p["observed_results"]["unitResults"][0].update(elementId="G999"),
    lambda p: p["recommended_segments"][0].update(price=1500),
    lambda p: p["recommended_segments"][1].update(start_power=35),
])
def test_unverified_or_incompatible_handoff_is_rejected(mutation):
    p = payload()
    mutation(p)
    response = TestClient(app).post("/api/pmss/manual-clearing-review", json=p)
    assert response.status_code == 422


def test_manual_result_review_does_not_expose_a_get_operation():
    client = TestClient(app)
    assert client.get("/api/pmss/manual-clearing-review").status_code == 405
    assert client.post("/api/pmss/manual-clearing-review", json={}).status_code == 422
