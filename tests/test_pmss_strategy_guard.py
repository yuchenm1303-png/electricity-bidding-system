"""Offline strategy guard tests use SYNTHETIC 2-bus cases, never protected PMSS data."""
from __future__ import annotations

import copy

import pytest
from test_historical_validation import _fixture

from powerbid.network_dispatch import DcOffer, dc_clear_hour, network_from_dict
from powerbid.pmss_integration import curve_for_period, snapshot_from_pmss
from powerbid.pmss_strategy_guard import assess_pmss_strategy_candidates


def _candidate(name: str, price: float) -> dict:
    return {
        "id": name, "name": name, "price_blocks": [[0, 100, price]],
        "score": 1e12, "expected_margin": 1e18,  # Must be ignored.
    }


def _case(day: int, original_bid_price: float = 60) -> dict:
    raw = _fixture(f"2025-09-{day:02d}")
    raw.pop("syntheticExample", None)
    raw["unitBids"]["G1"]["datas"][0]["segmentDatas"][0]["price"] = original_bid_price
    snap = snapshot_from_pmss(
        unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    grid = network_from_dict(raw["dcNetwork"])
    cleared = []
    for period in range(1, 25):
        offers = [
            DcOffer(unit.unit_id, index, block.quantity_mw, block.price)
            for unit in snap.units
            for index, block in enumerate(
                curve_for_period(snap.bids[unit.unit_id], period), start=1
            )
        ]
        cleared.append(dc_clear_hour(grid, offers, period))
    for row in raw["results"]["unitResults"]:
        row["accepted_mw"] = [
            hour.accepted_by_unit[row["unit_id"]] for hour in cleared
        ]
    for row in raw["results"]["nodalPrices"]:
        row["lmp"] = [hour.nodal_prices[row["element_id"]] for hour in cleared]
    for row in raw["results"]["branchFlows"]:
        row["flow_mw"] = [
            -hour.line_flows_mw[row["element_id"]] for hour in cleared
        ]
    return raw


def test_distinct_dates_not_independent_bids_and_no_live_profit_claim():
    days = [_case(1), _case(2), _case(3)]
    days[-1]["unitBids"]["G1"]["scopeId"] = "another-daily-scope"
    report = assess_pmss_strategy_candidates(days, [_candidate("均衡", 75)], "G1")
    assert report["training_case_dates"] == ["2025-09-01", "2025-09-02"]
    assert report["untouched_holdout_case_dates"] == ["2025-09-03"]
    assert report["original_bid_distinct_training_curves"] == 1
    assert report["holdout_reuses_training_original_bid_curve"] is True
    assert report["research_shortlist_candidate_ids"] == []
    assert report["model_confidence_grade"].startswith("C1_")
    target_days = report["target_unit_original_bid_historical_fit"]
    assert [row["case_date"] for row in target_days] == [
        "2025-09-01", "2025-09-02", "2025-09-03",
    ]
    assert all(row["target_unit_id"] == "G1" for row in target_days)
    assert all(row["dispatch_mae_mw"] == pytest.approx(0) for row in target_days)
    assert all(row["dispatch_coverage"] == 1.0 for row in target_days)
    assert all(row["max_abs_dispatch_error_mw"] == pytest.approx(0)
               for row in target_days)
    assert all(row["original_bid_only"] is True for row in target_days)
    assert all(row["new_bid_counterfactual_verified"] is False
               for row in target_days)
    assert report["recommended_for_real_pmss"] is None
    assert report["actual_pmss_counterfactual_profit_available"] is False
    assert report["historical_original_bid_validation"]["validated_new_bids"] is False
    assert all(row["dispatch_mae_mw"] == pytest.approx(0)
               for row in report["per_day_original_bid_simulation_vs_real_pmss"])
    assert report["candidates"][0]["score_training_only_0_to_100"] < 101
    assert report["candidates"][0]["real_pmss_candidate_profit_verified"] is False
    assert report["pmss_write_performed"] is False
    assert report["pmss_clearing_executed"] is False


def test_distinct_original_bids_unlock_only_research_shortlist():
    days = [_case(3, 70), _case(1, 60), _case(2, 65)]
    report = assess_pmss_strategy_candidates(
        days, [_candidate("收益优先", 75), _candidate("稳健", 65)], "G1",
    )
    assert report["model_confidence_grade"].startswith("C2_")
    assert report["holdout_reuses_training_original_bid_curve"] is False
    assert report["training_case_dates"] == ["2025-09-01", "2025-09-02"]
    assert report["historical_original_bid_validation"]["status"] == (
        "HISTORICAL_BASELINE_WITHIN_TOLERANCE"
    )
    assert report["research_shortlist_candidate_ids"]
    assert all(row["live_bid_allowed"] is False for row in report["candidates"])
    assert all(row["score_provenance"].endswith("RELATIVE_SCORE")
               for row in report["candidates"])
    assert report["full_unit_commitment_physics_verified"] is False


def test_zero_prices_illegal_price_and_decreasing_curve_block():
    candidates = [
        _candidate("全零", 0),
        _candidate("超限", 1500),
        {"id": "倒挂", "name": "倒挂", "segments": [
            {"start_power": 0, "end_power": 50, "price": 100},
            {"start_power": 50, "end_power": 100, "price": 50},
        ]},
    ]
    report = assess_pmss_strategy_candidates(
        [_case(1, 60), _case(2, 65), _case(3, 70)], candidates, "G1",
    )
    by_name = {row["candidate_name"]: row for row in report["candidates"]}
    assert "ALL_ZERO_PRICES" in by_name["全零"]["hard_blockers"]
    assert "CURVE_VIOLATES_CASE_RULES_OR_CAPACITY" in by_name["超限"]["hard_blockers"]
    assert "DECREASING_BLOCK_PRICES" in by_name["倒挂"]["hard_blockers"]
    assert all(row["score_training_only_0_to_100"] is None
               for row in report["candidates"])
    assert report["research_shortlist_candidate_ids"] == []


def test_holdout_price_error_blocks_research_even_when_training_is_perfect():
    days = [_case(1, 60), _case(2, 65), _case(3, 70)]
    days[-1]["results"]["nodalPrices"][0]["lmp"] = [800.0] * 24
    report = assess_pmss_strategy_candidates(days, [_candidate("均衡", 75)], "G1")
    assert report["historical_original_bid_validation"]["status"] == "NOT_VALIDATED"
    assert report["historical_original_bid_validation"]["holdout_nodal_price_mae"] > 100
    assert report["research_shortlist_candidate_ids"] == []


def test_reject_date_leakage_missing_real_results_and_false_candidates():
    days = [_case(1), _case(2), _case(3)]
    with pytest.raises(ValueError, match="Duplicate"):
        assess_pmss_strategy_candidates([days[0], days[0], days[2]],
                                        [_candidate("A", 70)], "G1")
    bad = copy.deepcopy(days)
    del bad[0]["results"]
    with pytest.raises(ValueError):
        assess_pmss_strategy_candidates(bad, [_candidate("A", 70)], "G1")
    with pytest.raises(ValueError, match="unique"):
        assess_pmss_strategy_candidates(
            days, [_candidate("A", 70), _candidate("A", 80)], "G1",
        )
    with pytest.raises(ValueError, match="finite"):
        assess_pmss_strategy_candidates(days, [_candidate("A", float("nan"))], "G1")


def test_api_strategy_guard_rejects_secrets_and_never_clears_pmss():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app.web_server import app

    client = TestClient(app)
    payload = {
        "history_cases": [_case(1), _case(2), _case(3)],
        "candidates": [_candidate("稳健", 75)],
        "target_unit_id": "G1",
    }
    ok = client.post("/api/pmss/strategy-guard", json=payload)
    assert ok.status_code == 200, ok.text
    assert ok.json()["pmss_clearing_executed"] is False
    assert ok.json()["recommended_for_real_pmss"] is None
    payload["history_cases"][0]["cookie"] = "do-not-echo-me"
    failure = client.post("/api/pmss/strategy-guard", json=payload)
    assert failure.status_code == 422
    assert "do-not-echo-me" not in failure.text
