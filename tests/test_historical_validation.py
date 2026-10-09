"""Multi-day historical DC validation: prevent one-day overconfidence."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from powerbid.historical_validation import (
    ValidationPolicy,
    judge_historical_model,
    validate_historical_day,
)
from powerbid.network_dispatch import DcOffer, dc_clear_hour, network_from_dict
from powerbid.pmss_integration import curve_for_period, snapshot_from_pmss

ROOT = Path(__file__).resolve().parents[1] / "data" / "examples"


def _fixture(date_label="2025-09-01"):
    original = json.loads((ROOT / "synthetic_dc_pmss.json").read_text("utf-8"))
    network_raw = json.loads((ROOT / "synthetic_dc_network.json").read_text("utf-8"))
    snapshot = snapshot_from_pmss(
        unit_tree=original["unitTree"],
        unit_bids=original["unitBids"],
        market_system=original["marketSystem"],
        demand_forecast_mw=original["demandForecastMw"],
        forecast_source=original["forecastSource"],
    )
    network = network_from_dict(network_raw)
    results = []
    for hour in range(1, 25):
        offers = []
        for unit in snapshot.units:
            blocks = curve_for_period(snapshot.bids[unit.unit_id], hour)
            for k, block in enumerate(blocks, 1):
                offers.append(DcOffer(unit.unit_id, k, block.quantity_mw, block.price))
        results.append(dc_clear_hour(network, offers, hour))

    original["historicalBacktestOnly"] = True
    original["caseDate"] = date_label
    original["dcNetwork"] = network_raw
    original["results"] = {
        "marketTypeAtom": "DA",
        "periodNum": 24,
        "unitResults": [
            {
                "unit_id": uid, "market_type": "DA",
                "accepted_mw": [row.accepted_by_unit[uid] for row in results],
            }
            for uid in ("G1", "G2")
        ],
        "nodalPrices": [
            {
                "element_id": bus, "market_type": "DA",
                "lmp": [row.nodal_prices[bus] for row in results],
            }
            for bus in ("A", "B")
        ],
        "branchFlows": [{
            "element_id": "LINE-AB", "market_type": "DA",
            # Deliberately reverse sign to exercise directional independence.
            "flow_mw": [-row.line_flows_mw["LINE-AB"] for row in results],
        }],
    }
    return original


def test_full_24h_baseline_fixture_has_zero_error_and_complete_coverage():
    day = validate_historical_day(_fixture())
    assert day.unit_count == 2
    assert day.bus_count == 2
    assert day.branch_count == 1
    assert len(day.grid_fingerprint) == 64
    for metric in (day.unit_dispatch, day.nodal_price, day.line_flow_abs):
        assert metric.coverage == 1.0
        assert metric.mae == pytest.approx(0.0, abs=1e-7)
    assert all(item.dispatch.mae == pytest.approx(0) for item in day.per_unit)
    assert all(item.metric.mae == pytest.approx(0) for item in day.per_node)
    assert all(item.metric.mae == pytest.approx(0) for item in day.per_branch)


def test_real_historical_errors_are_measured_not_hidden():
    case = _fixture()
    case["results"]["unitResults"][0]["accepted_mw"][1] += 15
    case["results"]["nodalPrices"][0]["lmp"][1] += 100
    case["results"]["branchFlows"][0]["flow_mw"][1] = 40
    day = validate_historical_day(case)
    assert day.unit_dispatch.observed_points == 48
    assert day.unit_dispatch.mae == pytest.approx(15 / 48)
    assert day.nodal_price.mae == pytest.approx(100 / 48)
    assert day.line_flow_abs.mae == pytest.approx(10 / 24)
    bus = next(x for x in day.per_node if x.element_id == "A")
    assert bus.metric.mae == pytest.approx(100 / 24)
    line = next(x for x in day.per_branch if x.element_id == "LINE-AB")
    assert line.metric.mae == pytest.approx(10 / 24)


def test_missing_values_never_become_zero():
    case = _fixture()
    case["results"]["unitResults"][0]["accepted_mw"][5] = None
    case["results"]["nodalPrices"][1]["lmp"][3] = None
    case["results"]["branchFlows"][0]["flow_mw"][8] = None
    day = validate_historical_day(case)
    assert day.unit_dispatch.observed_points == 47
    assert day.nodal_price.observed_points == 47
    assert day.line_flow_abs.observed_points == 23
    assert day.per_unit[0].dispatch.observed_points in (23, 24)


def test_history_requires_exact_original_ids_and_date():
    case = _fixture()
    case["results"]["unitResults"][0]["unit_id"] = "alien"
    with pytest.raises(ValueError, match="IDs disagree"):
        validate_historical_day(case)
    case = _fixture("yesterday")
    with pytest.raises(ValueError, match="ISO"):
        validate_historical_day(case)
    case = _fixture()
    case["historicalBacktestOnly"] = False
    with pytest.raises(ValueError, match="historical"):
        validate_historical_day(case)


def test_one_historical_case_cannot_pass_reliability_gate():
    day = validate_historical_day(_fixture())
    policy = ValidationPolicy(1.0, 1.0)
    result = judge_historical_model((day,), policy)
    assert result.status == "NOT_VALIDATED"
    assert not result.validated_new_bids
    assert result.holdout_case_dates == ("2025-09-01",)
    assert any("Insufficient" in why for why in result.reasons)


def test_held_out_last_day_uses_its_errors_not_train_sample_fit():
    baseline = validate_historical_day(_fixture("2025-09-01"))
    earlier = validate_historical_day(_fixture("2025-09-02"))
    bad = _fixture("2025-09-03")
    bad["results"]["nodalPrices"][0]["lmp"] = [800.0] * 24
    last = validate_historical_day(bad)
    policy = ValidationPolicy(5, 10, min_distinct_dates=3, holdout_dates=1)
    result = judge_historical_model((last, baseline, earlier), policy)
    assert result.status == "NOT_VALIDATED"
    assert result.holdout_case_dates == ("2025-09-03",)
    assert result.holdout_nodal_price_mae > 100
    assert any("Nodal price" in why for why in result.reasons)


def test_three_distinct_perfect_cases_only_validate_historical_baseline():
    rows = [
        validate_historical_day(_fixture(f"2025-09-{d:02d}"))
        for d in range(1, 4)
    ]
    result = judge_historical_model(rows, ValidationPolicy(2.0, 2.0))
    assert result.status == "HISTORICAL_BASELINE_WITHIN_TOLERANCE"
    assert result.evidence_days == 3
    assert result.holdout_case_dates == ("2025-09-03",)
    assert result.historical_only
    assert not result.validated_new_bids


def test_duplicate_dates_and_changed_lines_block_evidence():
    a = validate_historical_day(_fixture("2025-09-01"))
    with pytest.raises(ValueError, match="Duplicate"):
        judge_historical_model((a, a), ValidationPolicy(1, 1))
    b = replace(
        a, case_date="2025-09-02", grid_fingerprint="changed-topology"
    )
    c = replace(a, case_date="2025-09-03")
    result = judge_historical_model((a, b, c), ValidationPolicy(1, 1))
    assert result.status == "NOT_VALIDATED"
    assert any("topology" in reason for reason in result.reasons)


def test_missing_observations_fail_coverage_gate():
    cases = []
    for i in range(1, 4):
        sample = _fixture(f"2025-09-{i:02d}")
        if i == 3:
            sample["results"]["branchFlows"][0]["flow_mw"] = [None] * 24
        cases.append(validate_historical_day(sample))
    result = judge_historical_model(cases, ValidationPolicy(10, 10))
    assert result.status == "NOT_VALIDATED"
    assert result.flow_coverage == 0.0


def test_user_tolerances_are_explicit():
    with pytest.raises(ValueError):
        ValidationPolicy(-1, 100)
    with pytest.raises(ValueError):
        ValidationPolicy(10, 10, min_distinct_dates=2)
    with pytest.raises(ValueError):
        ValidationPolicy(10, 10, min_coverage=1.2)
