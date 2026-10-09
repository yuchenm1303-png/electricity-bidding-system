"""The public inspect response describes UC gaps without leaking source data."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from test_pmss_web_api import safe_snapshot  # noqa: E402

from app.web_server import app  # noqa: E402
from powerbid.pmss_integration import snapshot_from_pmss  # noqa: E402
from powerbid.pmss_scene_constraint_evidence import (  # noqa: E402
    summarize_scene_constraint_evidence,
)
from powerbid.pmss_technical_evidence import (  # noqa: E402
    sanitize_pmss_technical_evidence,
)

client = TestClient(app)


def _evidenced_snapshot():
    raw = safe_snapshot()
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    raw["technicalEvidence"] = sanitize_pmss_technical_evidence({
        "units": {"datas": [{
            "id": u.unit_id,
            "pdAdjustMax": u.capacity_mw,
            "minCapacity": u.min_power_mw,
            "minOnTime": 0, "minOffTime": 0,
            "incRate": 20, "decRate": 20, "launchCost": 0,
            "password": "DO_NOT_LEAK_PRIVATE_SOURCE",
        } for u in snapshot.units]},
    }, snapshot=snapshot)
    raw["sceneConstraintEvidence"] = summarize_scene_constraint_evidence(
        {"rowCount": 2, "datas": [
            {"ifConRamp": 1, "ifConInitPower": 0},
            {"ifConRamp": 0, "ifConInitPower": 1},
        ]},
        {"rowCount": 2, "datas": [
            {"initialState": "on", "power": 0, "keepTime": 10},
            {"initialState": "off", "power": 0, "keepTime": 6},
        ]},
        expected_units=2,
    )
    return raw


def test_inspect_exposes_verified_schema_and_specific_actionable_13_field_gaps():
    r = client.post("/api/pmss/inspect", json={"snapshot": _evidenced_snapshot()})
    assert r.status_code == 200, r.text
    body = r.json()
    proof = body["physical_evidence_gaps"]
    assert proof["unit_count"] == 2
    assert proof["fields_required_per_unit"] == 13
    assert proof["fields_with_any_anonymous_observations"] == 10
    assert proof["fields_missing_observations"] == 3
    assert proof["individually_verified_fields"] == 0
    assert proof["independent_technical_parameters_ready"] is False
    assert proof["scenario_switch_codes_interpreted"] is False
    assert proof["generator_initial_states_confirmed"] is False
    indexed = {item["field"]: item for item in proof["fields"]}
    assert indexed["ramp_up_mw"]["observed_source_field"] == "incRate"
    assert indexed["ramp_up_mw"]["model_unit"] == "MW/h"
    assert indexed["ramp_up_mw"]["usable_as_model_input"] is False
    assert indexed["startup_ramp_mw"]["status"] == "NO_FIELD_OBSERVATION"
    assert indexed["shutdown_cost"]["status"] == "NO_FIELD_OBSERVATION"
    assert "DO_NOT_LEAK_PRIVATE_SOURCE" not in r.text
    assert "initialState\": \"on" not in r.text


def test_inspect_without_observations_remains_blocked():
    r = client.post("/api/pmss/inspect", json={"snapshot": safe_snapshot()})
    assert r.status_code == 200, r.text
    proof = r.json()["physical_evidence_gaps"]
    assert proof["fields_with_any_anonymous_observations"] == 0
    assert proof["fields_missing_observations"] == 13


def test_inspect_refuses_poisoned_source_claim_and_never_promotes_evidence():
    raw = _evidenced_snapshot()
    raw["sceneConstraintEvidence"]["jointMilpReady"] = True
    r = client.post("/api/pmss/inspect", json={"snapshot": raw})
    assert r.status_code == 422
    raw = _evidenced_snapshot()
    raw["technicalEvidence"]["technicalInputsVerified"] = True
    r = client.post("/api/pmss/inspect", json={"snapshot": raw})
    assert r.status_code == 422
