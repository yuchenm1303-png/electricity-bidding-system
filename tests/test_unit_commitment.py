from dataclasses import replace

import pytest

from powerbid.unit_commitment import (
    ThermalConstraints,
    audit_dispatch,
    optimize_unit_commitment,
)


def _spec(**override):
    values = dict(
        unit_id="G1",
        min_mw=20.0,
        max_mw=100.0,
        ramp_up_mw=30.0,
        ramp_down_mw=30.0,
        startup_ramp_mw=40.0,
        shutdown_ramp_mw=40.0,
        min_up_hours=3,
        min_down_hours=2,
        startup_cost=100.0,
        shutdown_cost=15.0,
        initial_on=False,
        initial_mw=0.0,
        initial_state_hours=10,
    )
    return ThermalConstraints(**(values | override))


def test_dispatch_optimizer_has_24h_and_enforces_ramps_and_min_times():
    scipy = pytest.importorskip("scipy")
    assert scipy
    prices = [25.0] * 5 + [140.0] * 7 + [25.0] * 12
    spec = _spec()
    result = optimize_unit_commitment(
        spec,
        prices,
        energy_cost_per_mwh=50.0,
        forecast_source="synthetic test price forecast",
    )
    assert len(result.hourly) == 24
    assert result.total_energy_mwh > 0
    assert result.net_margin > 0
    assert result.terminal_mode == "complete"
    audit = audit_dispatch(spec, [hour.power_mw for hour in result.hourly])
    assert audit.feasible, audit.violations
    assert any(h.started for h in result.hourly)
    assert any(h.stopped for h in result.hourly)
    assert result.net_margin == pytest.approx(
        result.gross_margin - result.transition_cost, abs=1e-5
    )
    assert result.transition_cost == pytest.approx(
        sum(
            spec.startup_cost * h.started + spec.shutdown_cost * h.stopped
            for h in result.hourly
        )
    )


def test_initial_min_uptime_and_no_profitable_start():
    pytest.importorskip("scipy")
    spec = _spec(initial_on=True, initial_mw=30.0, initial_state_hours=1)
    result = optimize_unit_commitment(
        spec,
        [10.0] * 24,
        energy_cost_per_mwh=70.0,
        forecast_source="synthetic flat price",
    )
    assert result.hourly[0].online
    assert result.hourly[1].online
    assert all(not hour.online for hour in result.hourly[2:])
    assert not result.hourly[0].started
    assert result.hourly[2].stopped
    assert audit_dispatch(spec, [h.power_mw for h in result.hourly]).feasible


def test_all_unprofitable_can_remain_off():
    pytest.importorskip("scipy")
    result = optimize_unit_commitment(
        _spec(),
        [10.0] * 24,
        energy_cost_per_mwh=70.0,
        forecast_source="synthetic low price",
    )
    assert all(not h.online and h.power_mw == pytest.approx(0) for h in result.hourly)
    assert result.total_energy_mwh == pytest.approx(0)
    assert result.net_margin == pytest.approx(0)


def test_dispatch_audit_rejects_minimum_output_and_ramp_violations():
    spec = _spec()
    output = [0.0] * 24
    output[3] = 5.0
    output[4] = 100.0
    output[5] = 0.0
    audit = audit_dispatch(spec, output)
    assert not audit.feasible
    assert any("technical minimum" in x for x in audit.violations)
    assert any("upward ramp" in x for x in audit.violations)
    assert any("premature stop" in x for x in audit.violations)
    assert any("shutdown ramp" in x for x in audit.violations)


def test_pending_min_up_at_end_is_visible_for_carryover():
    spec = _spec()
    values = [0.0] * 23 + [20.0]
    carryover = audit_dispatch(spec, values, terminal_mode="carryover")
    complete = audit_dispatch(spec, values, terminal_mode="complete")
    assert carryover.feasible
    assert carryover.remaining_required_hours == 2
    assert not complete.feasible
    assert "terminal state" in complete.violations[-1]


def test_terminal_policy_must_be_explicit_and_valid():
    spec = _spec()
    with pytest.raises(ValueError, match="terminal_mode"):
        audit_dispatch(spec, [0.0] * 24, terminal_mode="unexpected")
    with pytest.raises(ValueError, match="24"):
        audit_dispatch(spec, [0.0], terminal_mode="complete")
    with pytest.raises(ValueError, match="physical"):
        replace(spec, ramp_up_mw=-1)


def test_zero_startup_ramp_prevents_online_dispatch_from_off():
    pytest.importorskip("scipy")
    spec = _spec(startup_ramp_mw=0)
    result = optimize_unit_commitment(
        spec,
        [150.0] * 24,
        energy_cost_per_mwh=60,
        forecast_source="synthetic",
    )
    assert all(not h.online for h in result.hourly)


def test_price_forecast_and_source_require_explicit_inputs():
    pytest.importorskip("scipy")
    spec = _spec()
    with pytest.raises(ValueError, match="24"):
        optimize_unit_commitment(spec, [50], energy_cost_per_mwh=40, forecast_source="test")
    with pytest.raises(ValueError, match="forecast_source"):
        optimize_unit_commitment(spec, [50] * 24, energy_cost_per_mwh=40, forecast_source="")
    with pytest.raises(ValueError, match="energy_cost"):
        optimize_unit_commitment(spec, [50] * 24, energy_cost_per_mwh=-1, forecast_source="test")
