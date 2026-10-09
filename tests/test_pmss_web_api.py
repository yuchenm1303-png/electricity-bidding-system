"""Contract and privacy checks for the React PMSS read-only analysis bridge."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.web_server import app  # noqa: E402

client = TestClient(app)


def _curve(price: int, quantity: int) -> dict:
    return {
        "datas": [{
            "startPeriod": 1,
            "endPeriod": 24,
            "segmentDatas": [{
                "startPower": 0, "endPower": quantity,
                "price": price, "segmentOrder": 1,
            }],
        }],
    }


def _metric(val: float) -> dict:
    return {"datas": [val] * 24}


def safe_snapshot() -> dict:
    return {
        "unitTree": [
            {"key": "G30", "title": "G30 燃煤", "leaf": True,
             "pdAdjustMax": 100, "pdAdjustMin": 0,
             "runningCost": 50, "unitType": "coal"},
            {"key": "G31", "title": "G31 燃气", "leaf": True,
             "pdAdjustMax": 200, "pdAdjustMin": 0,
             "runningCost": 70, "unitType": "gas"},
        ],
        "unitBids": {"G30": _curve(60, 100), "G31": _curve(80, 200)},
        "marketSystem": {
            "spotList": [{
                "marketAtomType": "DA",
                "unitPowerDeclareSegmentConstraint": 5,
                "priceLowerConstraint": 0,
                "priceUpperConstraint": 1000,
                "useSameBiddingCurve": 1,
            }]
        },
        "demandForecastMw": [180] * 24,
        "forecastSource": "PMSS historical DA scene input, not future load prediction",
        "historicalBacktestOnly": True,
        "caseDate": "2025-09-01",
        "loadSourceKind": "PMSS_DA_SCENE_LOAD_INPUT",
        "results": {
            "periodNum": 24,
            "marketTypeAtom": "DA",
            "unitResults": [{
                "elementId": "G30", "elementName": "G30", "marketTypeAtom": "DA",
                "power": _metric(90), "price": _metric(100), "income": _metric(9000),
            }],
            "nodalPrices": [{
                "elementId": "n1", "elementName": "Bus1", "marketTypeAtom": "DA",
                "powerFlow": _metric(100),
            }],
            "branchFlows": [{
                "elementId": "l1", "elementName": "Line1", "marketTypeAtom": "DA",
                "powerFlow": _metric(50),
                "beginNodePrice": _metric(100),
                "endNodePrice": _metric(90),
                "shadowPrice": _metric(10),
                "blockSurplus": _metric(500),
            }],
        },
    }


def test_pmss_inspection_returns_actual_data_without_pmss_calls():
    response = client.post("/api/pmss/inspect", json={"snapshot": safe_snapshot()})
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["units"]) == 2
    assert data["network"]["node_count"] == 1
    assert data["network"]["branch_count"] == 1
    assert data["network"]["hourly"][0]["lmp_spread"] == 0
    assert data["historical_only"] is True
    assert data["requires_explicit_pmss_validation"] is True


def test_pmss_five_segment_analysis_is_local_only():
    response = client.post("/api/pmss/optimize", json={
        "snapshot": safe_snapshot(),
        "target_unit_id": "G30",
        "candidate_prices": [0, 50, 70, 90],
        "iterations": 2,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["recommended"]["segments"]) == 5
    assert len(result["recommended"]["hours"]) == 24
    assert result["pmss_write_performed"] is False
    assert result["pmss_clearing_executed"] is False
    assert result["counterfactual_pmss_result_available"] is False
    assert result["baseline_backtest"]["observed_power_points"] == 24


def test_pmss_rejects_any_nested_secret_or_unknown_root_field():
    snapshot = safe_snapshot()
    snapshot["unitBids"]["G30"]["datas"][0]["cookie"] = "never send"
    response = client.post("/api/pmss/inspect", json={"snapshot": snapshot})
    assert response.status_code == 422
    snapshot = safe_snapshot()
    snapshot["unexpectedExport"] = True
    response = client.post("/api/pmss/inspect", json={"snapshot": snapshot})
    assert response.status_code == 422


def test_pmss_rejects_invalid_or_oversized_computation():
    payload = {
        "snapshot": safe_snapshot(), "target_unit_id": "G30",
        "candidate_prices": list(range(22)), "iterations": 2,
    }
    assert client.post("/api/pmss/optimize", json=payload).status_code == 422
    payload["candidate_prices"] = [60, 70]
    payload["iterations"] = 30
    assert client.post("/api/pmss/optimize", json=payload).status_code == 422
    response = client.post("/api/pmss/inspect", content="x" * 910_000,
                           headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_pmss_rejects_wrong_mime_and_does_not_expose_server_snapshot():
    response = client.post(
        "/api/pmss/inspect", content="{}", headers={"content-type": "text/plain"}
    )
    assert response.status_code == 415
    assert client.get("/api/pmss/inspect").status_code == 405
    assert client.get("/api/pmss/snapshot").status_code == 404


def _synthetic_network_case():
    case = safe_snapshot()
    case["dcNetwork"] = {
        "buses": ["A", "B"],
        "lines": [{
            "lineId": "L1", "fromBus": "A", "toBus": "B",
            "reactancePu": 0.1, "limitMw": 50,
        }],
        "unitBus": {"G30": "A", "G31": "B"},
        "hourlyDemandMw": {"A": [0] * 24, "B": [180] * 24},
        "slackBus": "A", "baseMva": 1,
        "topologySource": "synthetic 2-bus test; normalization only",
        "demandSource": case["forecastSource"],
    }
    return case


def test_react_pmss_network_evaluation_uses_existing_dc_engine():
    pytest.importorskip("scipy")
    case = _synthetic_network_case()
    inspected = client.post("/api/pmss/inspect", json={"snapshot": case})
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["dc_grid_available"] is True
    assert inspected.json()["dc_grid_buses"] == 2
    response = client.post("/api/pmss/network-evaluate", json={
        "snapshot": case, "target_unit_id": "G30",
        "recommended_segments": [
            {"start_power": 0, "end_power": 100, "price": 100},
        ],
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["baseline"]["hours"]) == 24
    assert len(data["recommended"]["hours"]) == 24
    assert data["baseline"]["hours"][0]["target_mw"] == pytest.approx(50)
    assert data["recommended"]["hours"][0]["target_mw"] == pytest.approx(0)
    assert data["baseline"]["hours_with_binding_lines"] == 24
    assert data["pmss_write_performed"] is False
    assert data["pmss_clearing_executed"] is False
    assert data["pmss_counterfactual_verified"] is False


def test_network_endpoint_refuses_missing_or_inconsistent_nodal_load():
    bare = safe_snapshot()
    assert client.post("/api/pmss/network-evaluate", json={
        "snapshot": bare, "target_unit_id": "G30",
    }).status_code == 422
    case = _synthetic_network_case()
    case["dcNetwork"]["hourlyDemandMw"]["B"][0] = 179
    assert client.post("/api/pmss/network-evaluate", json={
        "snapshot": case, "target_unit_id": "G30",
    }).status_code == 422
    assert client.get("/api/pmss/network-evaluate").status_code == 405

def test_real_historical_network_audit_appears_only_for_complete_original_day():
    pytest.importorskip("scipy")
    case = _synthetic_network_case()

    def series(ident, name, metric, value):
        return {
            "elementId": ident,
            "elementName": name,
            "marketTypeAtom": "DA",
            metric: {"datas": [value] * 24},
        }

    case["results"] = {
        "marketTypeAtom": "DA",
        "periodNum": 24,
        "unitResults": [
            series("G30", "G30", "power", 50),
            series("G31", "G31", "power", 130),
        ],
        "nodalPrices": [
            series("A", "BusA", "powerFlow", 60),
            series("B", "BusB", "powerFlow", 80),
        ],
        "branchFlows": [series("L1", "Line AB", "powerFlow", 50)],
    }
    case["results"]["unitResults"][0]["price"] = {"datas": [60] * 24}
    case["results"]["unitResults"][1]["price"] = {"datas": [80] * 24}
    response = client.post("/api/pmss/network-evaluate", json={
        "snapshot": case, "target_unit_id": "G30",
    })
    assert response.status_code == 200, response.text
    data = response.json()
    report = data["historical_grid_audit"]
    assert report["case_date"] == "2025-09-01"
    assert report["balanced_hour_count"] == 24
    assert report["bus_balance_mae_mw"] == pytest.approx(0)
    assert report["modeled_nodal_price_mae"] == pytest.approx(0)
    assert data["historical_unavailable_reason"] is None

    case["results"]["nodalPrices"].pop()
    response = client.post("/api/pmss/network-evaluate", json={
        "snapshot": case, "target_unit_id": "G30",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["historical_grid_audit"] is None
    assert data["historical_unavailable_reason"]


def test_current_rule_is_shown_even_if_saved_historical_bid_is_above_cap():
    raw = safe_snapshot()
    raw["unitBids"]["G30"]["datas"][0]["segmentDatas"][0]["price"] = 7000
    check = client.post("/api/pmss/inspect", json={"snapshot": raw})
    assert check.status_code == 200, check.text
    audit = check.json()["historical_bid_rule_audit"]
    assert audit["price_ceiling"] == 1000
    assert audit["original_units_outside_current_range"] == 1
    assert audit["original_segments_outside_current_range"] == 1
    assert audit["largest_original_price"] == 7000

    invalid = client.post("/api/pmss/optimize", json={
        "snapshot": raw, "target_unit_id": "G30",
        "candidate_prices": [100, 1001], "iterations": 1,
    })
    assert invalid.status_code == 422
    assert "market rule" in invalid.text

    valid = client.post("/api/pmss/optimize", json={
        "snapshot": raw, "target_unit_id": "G30",
        "candidate_prices": [100, 200, 1000], "iterations": 1,
    })
    assert valid.status_code == 200, valid.text
    assert all(s["price"] <= 1000 for s in valid.json()["recommended"]["segments"])


def test_network_counterfactual_rejects_above_ceiling_without_modifying_history():
    raw = _synthetic_network_case()
    raw["unitBids"]["G30"]["datas"][0]["segmentDatas"][0]["price"] = 7000
    reply = client.post("/api/pmss/network-evaluate", json={
        "snapshot": raw, "target_unit_id": "G30",
        "recommended_segments": [
            {"start_power": 0, "end_power": 100, "price": 8000},
        ],
    })
    assert reply.status_code == 422
    assert "market rule" in reply.text
    assert raw["unitBids"]["G30"]["datas"][0]["segmentDatas"][0]["price"] == 7000


def test_network_first_rank_uses_legal_curves_and_three_synthetic_peer_scenarios():
    pytest.importorskip("scipy")
    case = _synthetic_network_case()
    result = client.post("/api/pmss/network-rank", json={
        "snapshot": case, "target_unit_id": "G30",
        "risk_aversion": 0.6, "peer_price_deviation": 0.05,
    })
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["confidence_status"] == "RESEARCH_ONLY_NOT_OUT_OF_SAMPLE_VALIDATED"
    assert payload["validated_for_real_bidding"] is False
    assert payload["safe_for_live_submission"] is False
    assert payload["pmss_write_performed"] is False
    assert payload["pmss_clearing_executed"] is False
    assert len(payload["synthetic_scenarios"]) == 3
    assert payload["baseline_rule_compatible"] is True
    assert 1 <= len(payload["eligible_candidates"]) <= 4
    best = payload["best_candidate"]
    assert best["score"] == max(p["score"] for p in payload["eligible_candidates"])
    assert len(best["price_blocks"]) == 5
    assert all(0 <= p[2] <= 1000 for p in best["price_blocks"])


def test_network_first_rank_never_recommends_historical_above_cap_bid():
    pytest.importorskip("scipy")
    case = _synthetic_network_case()
    case["unitBids"]["G30"]["datas"][0]["segmentDatas"][0]["price"] = 7000
    result = client.post("/api/pmss/network-rank", json={
        "snapshot": case, "target_unit_id": "G30",
    })
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["baseline_rule_compatible"] is False
    assert payload["historical_units_outside_current_rule"] == 1
    assert payload["modeled_better_than_baseline"] is None
    assert all(0 <= p[2] <= 1000 for row in payload["eligible_candidates"]
               for p in row["price_blocks"])
    assert payload["safe_for_live_submission"] is False


def test_network_first_rank_rejects_no_grid_and_resource_abuse():
    case = safe_snapshot()
    response = client.post("/api/pmss/network-rank", json={
        "snapshot": case, "target_unit_id": "G30",
    })
    assert response.status_code == 422
    case = _synthetic_network_case()
    case["historicalBacktestOnly"] = False
    assert client.post("/api/pmss/network-rank", json={
        "snapshot": case, "target_unit_id": "G30",
    }).status_code == 422
    case["historicalBacktestOnly"] = True
    assert client.post("/api/pmss/network-rank", json={
        "snapshot": case, "target_unit_id": "G30",
        "risk_aversion": 1.1,
    }).status_code == 422
    assert client.get("/api/pmss/network-rank").status_code == 405


def test_pmss_inspect_joint_readiness_reports_missing_physical_parameters():
    raw = safe_snapshot()
    response = client.post("/api/pmss/inspect", json={"snapshot": raw})
    assert response.status_code == 200, response.text
    body = response.json()
    gate = body["joint_readiness"]
    assert gate["ready"] is False
    assert gate["total_units"] == len(body["units"])
    assert gate["supplied_units"] == 0
    assert set(gate["missing_unit_ids"]) == {
        unit["unit_id"] for unit in body["units"]
    }
    assert gate["independently_verified"] is False
    fields = body["joint_required_technical_fields"]
    for required in ("initial_on", "initial_mw", "initial_state_hours",
                     "ramp_up_mw", "min_up_hours", "startup_cost"):
        assert required in fields
    assert "runningCost" not in fields


def test_scene_constraint_summary_is_read_only_and_never_unlocks_real_joint_milp():
    from powerbid.pmss_scene_constraint_evidence import (
        summarize_scene_constraint_evidence,
    )

    raw = safe_snapshot()
    before = client.post("/api/pmss/inspect", json={"snapshot": raw})
    assert before.status_code == 200, before.text
    count = len(before.json()["units"])
    assert before.json()["scene_constraint_evidence"] is None
    calc = {
        "rowCount": count,
        "datas": [
            {"ifConRamp": "1", "ifConMinOnOffTm": "0"}
            for _ in range(count)
        ],
    }
    initial = {
        "rowCount": count,
        "datas": [
            {"initialState": 1, "keepTime": 120, "power": 0}
            for _ in range(count)
        ],
    }
    report = summarize_scene_constraint_evidence(
        calc, initial, expected_units=count
    )
    raw["sceneConstraintEvidence"] = report
    response = client.post("/api/pmss/inspect", json={"snapshot": raw})
    assert response.status_code == 200, response.text
    data = response.json()
    scene = data["scene_constraint_evidence"]
    assert scene["constraint_rows"] == count
    assert scene["initial_rows"] == count
    assert scene["switches"]["ifConRamp"]["value_1"] == count
    assert scene["switches"]["ifConMinOnOffTm"]["value_0"] == count
    assert scene["joint_milp_ready"] is False
    assert data["joint_readiness"]["ready"] is False

    raw["sceneConstraintEvidence"]["jointMilpReady"] = True
    bad = client.post("/api/pmss/inspect", json={"snapshot": raw})
    assert bad.status_code == 422
    raw["sceneConstraintEvidence"]["jointMilpReady"] = False
    raw["sceneConstraintEvidence"]["sensitiveToken"] = "example"
    blocked = client.post("/api/pmss/inspect", json={"snapshot": raw})
    assert blocked.status_code == 422
