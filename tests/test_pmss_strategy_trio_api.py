"""Public API contract: local profile generation never gains PMSS-write rights."""
import pytest
from test_pmss_web_api import _synthetic_network_case, client


def test_strategy_trio_api_marks_unknown_physics_without_inputs():
    pytest.importorskip("scipy")
    request = {
        "snapshot": _synthetic_network_case(),
        "target_unit_id": "G30",
    }
    response = client.post("/api/pmss/strategy-trio", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["profile"] for c in body["candidates"]] == ["收益优先", "均衡", "稳健"]
    assert body["missing_physical_unit_ids"] == ["G30", "G31"]
    assert body["safe_for_live_submission"] is False
    assert body["pmss_write_performed"] is False
    assert body["pmss_clearing_executed"] is False
    assert body["historical_original_bid_is_candidate"] is False
    assert all(c["local_candidate_usable"] is False for c in body["candidates"])


def test_strategy_trio_api_denies_missing_network_and_unlabeled_uc_inputs():
    case = _synthetic_network_case()
    without_grid = dict(case)
    without_grid.pop("dcNetwork")
    assert client.post("/api/pmss/strategy-trio", json={
        "snapshot": without_grid, "target_unit_id": "G30"
    }).status_code == 422
    assert client.post("/api/pmss/strategy-trio", json={
        "snapshot": case, "target_unit_id": "G30",
        "technical_source": "synthetic"
    }).status_code == 422
    assert client.post("/api/pmss/strategy-trio", json={
        "snapshot": case, "target_unit_id": "G30",
        "technical": {"G30": {"unit_id": "G30"}},
        "technical_source": "synthetic",
        "technical_source_description": "Incomplete arbitrary assumptions",
    }).status_code == 422


def test_strategy_trio_api_rejects_untrusted_historical_and_nan():
    case = _synthetic_network_case()
    case["historicalBacktestOnly"] = False
    assert client.post("/api/pmss/strategy-trio", json={
        "snapshot": case, "target_unit_id": "G30"
    }).status_code == 422
    case["historicalBacktestOnly"] = True
    assert client.post("/api/pmss/strategy-trio", json={
        "snapshot": case, "target_unit_id": "G30",
        "peer_price_deviation": 0.2
    }).status_code == 422
