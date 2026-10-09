"""HTTP contract: no inferred UC data, no PMSS write, coupled bounds only."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from test_pmss_web_api import _synthetic_network_case  # noqa: E402

from app.web_server import app  # noqa: E402

client = TestClient(app)


def _technical():
    return {
        key: {
            "unit_id": key, "min_mw": 0, "max_mw": max_mw,
            "ramp_up_mw": max_mw, "ramp_down_mw": max_mw,
            "startup_ramp_mw": max_mw, "shutdown_ramp_mw": max_mw,
            "min_up_hours": 1, "min_down_hours": 1,
            "startup_cost": 0, "shutdown_cost": 0,
            "initial_on": True, "initial_mw": initial_mw,
            "initial_state_hours": 10,
        }
        for key, max_mw, initial_mw in (
            ("G30", 100, 0), ("G31", 200, 180)
        )
    }


def _payload():
    return {
        "snapshot": _synthetic_network_case(),
        "target_unit_id": "G30",
        "recommended_segments": [
            {"start_power": 0, "end_power": 100, "price": 80},
        ],
        "technical": _technical(),
        "technical_source": "synthetic",
        "technical_source_description": "Two generator all-assumption training fixture",
        "terminal_mode": "carryover",
    }


def test_synthetic_joint_endpoint_shows_24h_physical_envelope_not_pmss_truth():
    reply = client.post("/api/pmss/network-joint-mwh-range", json=_payload())
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["minimum_accepted_mwh"] == pytest.approx(0, abs=0.1)
    assert data["maximum_accepted_mwh"] == pytest.approx(1200, abs=0.1)
    assert len(data["maximum_24h_dispatch_mw"]) == 24
    assert all(value <= 50.001 for value in data["maximum_24h_dispatch_mw"])
    assert data["independent_pmss_technical_verification"] is False
    assert data["counterfactual_pmss_verified"] is False
    assert data["safe_for_live_submission"] is False
    assert data["pmss_write_performed"] is False
    assert data["pmss_clearing_executed"] is False
    assert data["study_only"] is True
    assert data["readiness"]["source"] == "synthetic"


@pytest.mark.parametrize("mutation", [
    lambda p: p.update({"technical": {"G30": p["technical"]["G30"]}}),
    lambda p: p["technical"]["G30"].pop("startup_ramp_mw"),
    lambda p: p["technical"]["G30"].update({"initial_on": 1}),
    lambda p: p.update({"technical_source": "user_supplied_unverified"}),
    lambda p: p.update({"technical_source_description": ""}),
    lambda p: p.update({"recommended_segments": [{
        "start_power": 0, "end_power": 100, "price": 1001,
    }]}),
    lambda p: p["snapshot"].pop("dcNetwork"),
    lambda p: p["snapshot"].update({"historicalBacktestOnly": False}),
    lambda p: p["technical"]["G30"].update({"token": "do-not-accept"}),
])
def test_joint_endpoint_blocks_missing_guessed_or_unverified_data(mutation):
    payload = _payload()
    mutation(payload)
    response = client.post("/api/pmss/network-joint-mwh-range", json=payload)
    assert response.status_code == 422, response.text


def test_joint_rejects_get_or_unsupported_empty_body():
    assert client.get("/api/pmss/network-joint-mwh-range").status_code == 405
    response = client.post("/api/pmss/network-joint-mwh-range", json={})
    assert response.status_code == 422
