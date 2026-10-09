"""Real HTTP route contract for legal candidate optimal-dispatch uncertainty."""
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


def _payload(price=80):
    return {
        "snapshot": _synthetic_network_case(),
        "target_unit_id": "G30",
        "recommended_segments": [
            {"start_power": 0, "end_power": 100, "price": price},
        ],
    }


def test_new_endpoint_reports_finite_interval_and_never_pmss_approval():
    response = client.post("/api/pmss/network-dispatch-range", json=_payload())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ambiguous_hours"] == 24
    assert result["minimum_accepted_mwh"] == pytest.approx(0, abs=1e-3)
    assert result["maximum_accepted_mwh"] == pytest.approx(24*50, abs=1e-3)
    assert result["hours"][0]["range_width_mw"] == pytest.approx(50, abs=1e-3)
    assert result["counterfactual_pmss_verified"] is False
    assert result["uses_historical_outcomes_as_forecast"] is False
    assert result["safe_for_live_submission"] is False
    assert result["pmss_write_performed"] is False
    assert result["pmss_clearing_executed"] is False
    assert result["study_only"] is True
    assert "lmp" not in str(result["hours"][0]).lower()


def test_api_refuses_illegal_new_bid_even_if_saved_history_contains_high_prices():
    for price in (-1, 1001, 7000):
        response = client.post(
            "/api/pmss/network-dispatch-range", json=_payload(price)
        )
        assert response.status_code == 422, response.text


def test_api_requires_new_offer_valid_network_and_history_label():
    request = _payload()
    del request["recommended_segments"]
    assert client.post(
        "/api/pmss/network-dispatch-range", json=request
    ).status_code == 422
    request = _payload()
    del request["snapshot"]["dcNetwork"]
    assert client.post(
        "/api/pmss/network-dispatch-range", json=request
    ).status_code == 422
    request = _payload()
    request["snapshot"]["historicalBacktestOnly"] = False
    assert client.post(
        "/api/pmss/network-dispatch-range", json=request
    ).status_code == 422


def test_api_refuses_nested_credential_fields_and_get():
    request = _payload()
    request["snapshot"]["unitTree"][0]["token"] = "NEVER_UPLOAD"
    assert client.post(
        "/api/pmss/network-dispatch-range", json=request
    ).status_code == 422
    assert client.get("/api/pmss/network-dispatch-range").status_code == 405
