"""Tests for post-clearing physical diagnostic, not PMSS market feasibility."""
from dataclasses import replace

import pytest
from test_strategy_lab import _snapshot

from powerbid.physical_strategy_audit import (
    best_physical_candidate,
    screen_strategy_results,
)
from powerbid.strategy_lab import DemandStress, compare_strategies
from powerbid.unit_commitment import ThermalConstraints


def _physical(**overrides):
    values = dict(
        unit_id="G1",
        min_mw=15.0,
        max_mw=100.0,
        ramp_up_mw=100.0,
        ramp_down_mw=100.0,
        startup_ramp_mw=100.0,
        shutdown_ramp_mw=100.0,
        min_up_hours=1,
        min_down_hours=1,
        startup_cost=50.0,
        shutdown_cost=0.0,
        initial_on=True,
        initial_mw=100.0,
        initial_state_hours=10,
    )
    return ThermalConstraints(**(values | overrides))


def test_screened_policy_probabilities_stay_within_one_and_are_grounded():
    result = compare_strategies(
        _snapshot(),
        "G1",
        markups=(0.0, 10.0),
        scenarios=(DemandStress("normal"), DemandStress("high", 1.05)),
    )
    audits = screen_strategy_results(result.ranked, _physical())
    assert len(audits) == result.evaluated
    assert all(0 <= item.physically_feasible_probability <= 1 for item in audits)
    assert all(item.scenario_count == 2 for item in audits)
    assert best_physical_candidate(audits) is not None


def test_screen_rejects_physically_unrealistic_minimum():
    result = compare_strategies(
        replace(_snapshot(), demand_forecast_mw=(50.0,) * 24),
        "G1",
        markups=(0.0,),
        scenarios=(DemandStress("normal"),),
    )
    impossible = _physical(min_mw=99.0, initial_mw=100.0)
    audits = screen_strategy_results(result.ranked, impossible)
    assert any(x.physically_feasible_probability == 0 for x in audits)
    rejected = next(x for x in audits if x.physically_feasible_probability == 0)
    assert any("technical minimum" in message for message in rejected.sample_violations)


def test_screen_rejects_trajectory_with_violated_ramp():
    snap = _snapshot(same_curve=False, high_load=True)
    result = compare_strategies(
        snap,
        "G1",
        markups=(0.0, 50.0),
        scenarios=(DemandStress("normal"),),
    )
    physical = _physical(
        ramp_up_mw=1.0, ramp_down_mw=1.0,
        startup_ramp_mw=1.0, shutdown_ramp_mw=1.0,
    )
    audits = screen_strategy_results(result.ranked, physical)
    assert any(x.physically_feasible_probability == 0 for x in audits)
    assert all(x.scenario_count == 1 for x in audits)


def test_screen_limits_examples_and_rejects_invalid_limit():
    result = compare_strategies(
        _snapshot(), "G1", markups=(0,),
        scenarios=(DemandStress("normal"),),
    )
    with pytest.raises(ValueError, match="maximum_examples"):
        screen_strategy_results(result.ranked, _physical(), maximum_examples=-1)
    report = screen_strategy_results(
        result.ranked, _physical(min_mw=99.0), maximum_examples=1
    )
    assert all(len(x.sample_violations) <= 1 for x in report)
