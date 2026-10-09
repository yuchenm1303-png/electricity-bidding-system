"""Strictly primary-cost-preserving and reproducible DC tie-break tests."""
import pytest
from test_historical_validation import _fixture

from powerbid.deterministic_dc_tiebreak import select_dc_optimal_tiebreak
from powerbid.historical_tiebreak_audit import audit_historical_tiebreaks
from powerbid.network_dispatch import DcLine, DcNetwork, DcOffer


def _onebus():
    return DcNetwork(
        buses=("BUS",), lines=(), unit_bus={"G1": "BUS", "G2": "BUS"},
        hourly_demand_mw={"BUS": (80.,)*24}, slack_bus="BUS",
        base_mva=100, topology_source="synthetic", demand_source="synthetic",
    )


def test_equal_price_ex_ante_unit_priority_selects_two_different_stable_optima():
    offers = (DcOffer("G2", 1, 100, 50), DcOffer("G1", 1, 100, 50))
    asc = select_dc_optimal_tiebreak(
        _onebus(), offers, 1, unit_priority=("G1", "G2")
    )
    desc = select_dc_optimal_tiebreak(
        _onebus(), offers, 1, unit_priority=("G2", "G1")
    )
    assert asc.selected_mw["G1"] == pytest.approx(80)
    assert asc.selected_mw["G2"] == pytest.approx(0)
    assert desc.selected_mw["G1"] == pytest.approx(0)
    assert desc.selected_mw["G2"] == pytest.approx(80)
    assert asc.primary_optimum_bid_cost == pytest.approx(4000)
    assert desc.selected_bid_cost == pytest.approx(4000)
    assert "NOT proven PMSS" in asc.disclaimer


def test_bid_file_order_does_not_change_canonical_secondary_dispatch():
    offers = (DcOffer("G1", 1, 60, 50), DcOffer("G1", 2, 40, 50),
              DcOffer("G2", 1, 100, 50))
    a = select_dc_optimal_tiebreak(_onebus(), offers, 1)
    b = select_dc_optimal_tiebreak(_onebus(), tuple(reversed(offers)), 1)
    assert a.selected_mw == pytest.approx(b.selected_mw)
    assert a.line_flows_mw == b.line_flows_mw
    assert a.original_model_nodal_prices == b.original_model_nodal_prices


def test_expensive_offer_cannot_be_preferred_over_cheaper_bid():
    offers = (DcOffer("G1", 1, 100, 100), DcOffer("G2", 1, 100, 10))
    result = select_dc_optimal_tiebreak(
        _onebus(), offers, 1, unit_priority=("G1", "G2")
    )
    assert result.selected_mw["G2"] == pytest.approx(80, abs=1e-4)
    assert result.selected_mw["G1"] == pytest.approx(0, abs=1e-4)
    assert result.selected_bid_cost <= result.primary_optimum_bid_cost + (
        result.allowed_primary_cost_increase + 1e-5
    )


def test_network_congestion_remains_enforced_after_secondary_priority():
    grid = DcNetwork(
        buses=("A", "B"),
        lines=(DcLine("AB", "A", "B", 0.1, 30),),
        unit_bus={"G1": "A", "G2": "B"},
        hourly_demand_mw={"A": (0.,)*24, "B": (80.,)*24},
        slack_bus="A", base_mva=100, topology_source="synthetic",
        demand_source="synthetic",
    )
    bids = (DcOffer("G1", 1, 100, 50), DcOffer("G2", 1, 100, 50))
    result = select_dc_optimal_tiebreak(
        grid, bids, 1, unit_priority=("G1", "G2")
    )
    assert result.selected_mw["G1"] == pytest.approx(30)
    assert result.selected_mw["G2"] == pytest.approx(50)
    assert result.line_flows_mw["AB"] == pytest.approx(30)


def test_priority_and_tolerance_are_strict_and_nonhistorical():
    bids = (DcOffer("G1", 1, 100, 50), DcOffer("G2", 1, 100, 50))
    with pytest.raises(ValueError, match="exactly once"):
        select_dc_optimal_tiebreak(_onebus(), bids, 1, unit_priority=("G1", "G1"))
    with pytest.raises(ValueError, match="cost tolerance"):
        select_dc_optimal_tiebreak(_onebus(), bids, 1, max_cost_increase_abs=-1)
    with pytest.raises(ValueError, match="finite positive"):
        select_dc_optimal_tiebreak(_onebus(), bids, 1, time_limit_seconds=0)


def test_historical_comparison_never_chooses_or_claims_platform_tie_policy():
    report = audit_historical_tiebreaks(_fixture())
    assert report.examined_hours == 24
    assert report.compared_hours == 24
    assert report.generator_count == 2
    assert report.baseline_dispatch_mae_mw == pytest.approx(0)
    assert "not PMSS" in report.disclaimer.lower() or "not PMSS" in report.disclaimer
    assert report.maximum_primary_bid_cost_increase < 1e-3


def test_historical_input_only_and_missing_observations_refuse_imputation():
    sample = _fixture()
    sample["results"]["unitResults"][0]["accepted_mw"][3] = None
    report = audit_historical_tiebreaks(sample)
    assert report.compared_hours == 23
    assert report.hours[3].baseline_mae_mw is None
    sample["historicalBacktestOnly"] = False
    with pytest.raises(ValueError, match="historical"):
        audit_historical_tiebreaks(sample)
