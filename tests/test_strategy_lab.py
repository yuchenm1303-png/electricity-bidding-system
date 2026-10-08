"""Behavior and safety tests for standalone 24h bidding-policy comparisons."""
from dataclasses import replace

import pytest

from powerbid.pmss_integration import (
    BidSegment,
    GeneratorSpec,
    MarketLimits,
    PeriodBid,
    PMSSSnapshot,
    curve_for_period,
)
from powerbid.strategy_lab import (
    BidPolicy,
    DemandStress,
    _lower_tail,
    compare_strategies,
    evaluate_strategy,
    generate_policy_plan,
    simulate_strategy,
    stress_grid,
)


def _snapshot(*, same_curve=True, high_load=False):
    loads = (100.0,) * 12 + (200.0,) * 12 if high_load else (160.0,) * 24
    return PMSSSnapshot(
        units=(
            GeneratorSpec("G1", "target", 100.0, 15.0, 50.0, "coal"),
            GeneratorSpec("G2", "peer", 150.0, 0.0, 80.0, "gas"),
        ),
        bids={
            "G1": (PeriodBid(1, 24, (BidSegment(0.0, 100.0, 60.0),)),),
            "G2": (PeriodBid(1, 24, (BidSegment(0.0, 150.0, 90.0),)),),
        },
        demand_forecast_mw=loads,
        forecast_source="explicit synthetic demand fixture",
        limits=MarketLimits(
            market_type="DA",
            max_segments=5,
            price_floor=0.0,
            price_ceiling=1000.0,
            same_curve=same_curve,
        ),
    )


def test_cost_policy_uses_technical_minimum_as_a_price_band_break():
    snap = _snapshot()
    plan = generate_policy_plan(snap, "G1", BidPolicy("marginal cost"))
    assert len(plan) == 1
    assert plan[0].start_period == 1
    assert plan[0].end_period == 24
    blocks = plan[0].segments
    assert len(blocks) == 5
    assert blocks[0] == BidSegment(0.0, 15.0, 50.0)
    assert blocks[-1].end_power == 100.0
    assert all(block.price == 50.0 for block in blocks)


def test_independent_hours_only_when_rule_allows_them():
    snap = _snapshot(same_curve=False, high_load=True)
    plan = generate_policy_plan(
        snap, "G1", BidPolicy("responsive", markup=20.0, slope=10.0, scarcity_sensitivity=100.0)
    )
    assert len(plan) == 24
    assert all(p.start_period == p.end_period for p in plan)
    morning = curve_for_period(plan, 1)[0].price
    evening = curve_for_period(plan, 23)[0].price
    assert evening > morning

    shared = replace(snap, limits=replace(snap.limits, same_curve=True))
    common = generate_policy_plan(
        shared, "G1", BidPolicy("responsive", 20.0, 10.0, 100.0)
    )
    assert len(common) == 1
    assert curve_for_period(common, 1) == curve_for_period(common, 23)


def test_unmodified_baseline_reclears_using_peers_and_real_hour_count():
    snap = _snapshot()
    hours = simulate_strategy(snap, "G1", snap.bids["G1"], DemandStress("normal"))
    assert len(hours) == 24
    assert all(h.feasible for h in hours)
    assert all(h.accepted_mw == pytest.approx(100.0) for h in hours)
    assert all(h.clearing_price == pytest.approx(90.0) for h in hours)
    assert sum(h.profit for h in hours) == pytest.approx(96000.0)


def test_peer_price_stress_changes_clearing_but_does_not_change_snapshot():
    snap = _snapshot()
    before = snap.bids["G2"][0].segments[0].price
    normal = simulate_strategy(snap, "G1", snap.bids["G1"], DemandStress("normal"))
    raised = simulate_strategy(
        snap, "G1", snap.bids["G1"], DemandStress("expensive peers", peer_price_factor=1.2)
    )
    assert raised[0].clearing_price > normal[0].clearing_price
    assert snap.bids["G2"][0].segments[0].price == before


def test_risk_scenarios_are_synthetic_and_probabilities_normalize():
    snap = _snapshot()
    scenarios = (
        DemandStress("normal", probability=3),
        DemandStress("higher load", demand_factor=1.1, probability=1),
    )
    result = evaluate_strategy(snap, "G1", "baseline", snap.bids["G1"], scenarios)
    assert [s.probability for s in result.scenarios] == pytest.approx([0.75, 0.25])
    assert result.expected_profit == pytest.approx(
        0.75 * result.scenarios[0].total_profit
        + 0.25 * result.scenarios[1].total_profit
    )
    assert len(stress_grid()) == 9


def test_comparison_includes_baseline_and_enforces_feasibility():
    snap = _snapshot(same_curve=False, high_load=True)
    result = compare_strategies(
        snap, "G1", markups=(0, 20, 60), scenarios=stress_grid(demand_deviation=0.05)
    )
    assert result.evaluated == 10
    assert result.baseline.name.startswith("平台已有报价")
    assert len(result.ranked) == 10
    assert result.recommended.feasible_probability == pytest.approx(1.0)
    assert len(result.recommended.scenarios[0].hours) == 24
    assert all(p.start_period == p.end_period for p in result.recommended.periods) or (
        result.recommended.name == result.baseline.name
    )


def test_no_plan_is_recommended_when_the_system_cannot_serve_load():
    snap = replace(_snapshot(), demand_forecast_mw=(450.0,) * 24)
    with pytest.raises(ValueError, match="No plan serves every stress scenario"):
        compare_strategies(snap, "G1", markups=(0, 30))


def test_invalid_gaps_and_over_capacity_rejected_before_scoring():
    snap = _snapshot()
    gap = (PeriodBid(
        1, 24, (BidSegment(0, 10, 40), BidSegment(12, 100, 50))
    ),)
    with pytest.raises(ValueError, match="Non-contiguous"):
        simulate_strategy(snap, "G1", gap, DemandStress("normal"))
    too_big = (PeriodBid(1, 24, (BidSegment(0, 110, 55),)),)
    with pytest.raises(ValueError, match="exceeds"):
        simulate_strategy(snap, "G1", too_big, DemandStress("normal"))


def test_invalid_policy_or_stress_parameters_fail_closed():
    with pytest.raises(ValueError):
        BidPolicy("bad", markup=float("nan"))
    with pytest.raises(ValueError):
        DemandStress("bad", demand_factor=0)
    with pytest.raises(ValueError):
        stress_grid(demand_deviation=1)
    with pytest.raises(ValueError):
        compare_strategies(_snapshot(), "G1", markups=(-10,))
    with pytest.raises(ValueError):
        evaluate_strategy(_snapshot(), "G1", "test", _snapshot().bids["G1"], [])


def test_lower_tail_produces_stable_cvar_for_entire_day():
    snap = _snapshot()
    ev = evaluate_strategy(
        snap,
        "G1",
        "benchmark",
        snap.bids["G1"],
        (DemandStress("normal"), DemandStress("high peer", peer_price_factor=1.2)),
        risk_aversion=1.0,
        tail_fraction=0.5,
    )
    assert ev.downside_profit == pytest.approx(min(x.total_profit for x in ev.scenarios))
    assert ev.score == pytest.approx(ev.downside_profit)
    assert _lower_tail(ev.scenarios, 1.0) == pytest.approx(ev.expected_profit)
