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
