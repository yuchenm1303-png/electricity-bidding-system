"""Mixed integer 24-hour nodal dispatch tests: physical and network jointly."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from powerbid.joint_market import JointInfeasibleError, joint_clear_day
from powerbid.network_dispatch import DcLine, DcNetwork, network_from_dict
from powerbid.pmss_integration import (
    BidSegment,
    PeriodBid,
    snapshot_from_pmss,
)
from powerbid.unit_commitment import ThermalConstraints, audit_dispatch

EXAMPLES = Path(__file__).resolve().parents[1] / "data" / "examples"


def _model():
    data = json.loads((EXAMPLES / "synthetic_dc_pmss.json").read_text("utf-8"))
    net = json.loads((EXAMPLES / "synthetic_dc_network.json").read_text("utf-8"))
    snapshot = snapshot_from_pmss(
        unit_tree=data["unitTree"],
        unit_bids=data["unitBids"],
        market_system=data["marketSystem"],
        demand_forecast_mw=data["demandForecastMw"],
        forecast_source=data["forecastSource"],
    )
    network = network_from_dict(net)
    units = {
        "G1": ThermalConstraints(
            unit_id="G1", min_mw=15, max_mw=100,
            ramp_up_mw=30, ramp_down_mw=30,
            startup_ramp_mw=40, shutdown_ramp_mw=40,
            min_up_hours=3, min_down_hours=2,
            startup_cost=100, shutdown_cost=5,
            initial_on=True, initial_mw=30, initial_state_hours=10,
        ),
        "G2": ThermalConstraints(
            unit_id="G2", min_mw=0, max_mw=150,
            ramp_up_mw=150, ramp_down_mw=150,
            startup_ramp_mw=150, shutdown_ramp_mw=150,
            min_up_hours=1, min_down_hours=1,
            startup_cost=200, shutdown_cost=5,
            initial_on=True, initial_mw=130, initial_state_hours=10,
        ),
    }
    return snapshot, network, units


def test_joint_solver_network_congestion_and_fixed_commitment_pricing():
    snapshot, network, units = _model()
    result = joint_clear_day(snapshot, network, units, "G1")
    assert len(result.hours) == 24
    assert result.pricing_method == "fixed-commitment continuous LP duals"
    assert result.model_label.endswith("NOT PMSS market clearing")
    for h in result.hours:
        assert h.accepted_by_unit["G1"] == pytest.approx(30, abs=1e-5)
        assert h.accepted_by_unit["G2"] == pytest.approx(130, abs=1e-5)
        assert h.line_flows_mw["LINE-AB"] == pytest.approx(30, abs=1e-5)
        assert h.nodal_prices["A"] == pytest.approx(60, abs=1e-5)
        assert h.nodal_prices["B"] == pytest.approx(90, abs=1e-5)
        assert h.demand_mw == pytest.approx(160)
        assert h.unit_online == {"G1": True, "G2": True}
        assert not any(h.unit_started.values())
    assert result.total_bid_energy_cost == pytest.approx(24 * (30 * 60 + 130 * 90))
    assert result.total_transition_cost == pytest.approx(0)
    assert result.total_objective_cost == pytest.approx(
        result.total_bid_energy_cost + result.total_transition_cost
    )


def test_network_line_congestion_prevents_infeasible_high_demand():
    snapshot, network, units = _model()
    blocked = replace(
        network,
        lines=(DcLine("LINE-AB", "A", "B", 0.1, 5),),
    )
    with pytest.raises(JointInfeasibleError, match="No 24-hour dispatch"):
        joint_clear_day(snapshot, blocked, units, "G1")


def test_network_price_bid_change_reoptimized_under_24h_commitment():
    snapshot, network, units = _model()
    new_bid = (PeriodBid(1, 24, (BidSegment(0, 100, 95),)),)
    result = joint_clear_day(
        snapshot, network, units, "G1", candidate_plan=new_bid
    )
    assert len(result.hours) == 24
    assert result.hours[0].accepted_by_unit["G1"] < 30
    assert result.hours[0].accepted_by_unit["G1"] >= units["G1"].min_mw
    assert result.hours[0].nodal_prices["B"] == pytest.approx(90)
    assert snapshot.bids["G1"][0].segments[0].price == 60


def test_all_units_need_verified_technical_constraints():
    snapshot, network, units = _model()
    with pytest.raises(ValueError, match="Every PMSS generator"):
        joint_clear_day(snapshot, network, {"G1": units["G1"]}, "G1")
    with pytest.raises(ValueError, match="exceeds snapshot capacity"):
        joint_clear_day(
            snapshot, network,
            units | {"G1": replace(units["G1"], max_mw=150)}, "G1"
        )


def test_joint_milp_ramp_and_unit_start_are_enforced_over_day():
    snapshot, _, specs = _model()
    # Both units serve the same bus, with one cheap unit initially offline.
    load = (20.0,) * 4 + (80.0,) * 7 + (0.0,) * 13
    snapshot = replace(snapshot, demand_forecast_mw=load)
    network = DcNetwork(
        buses=("A",),
        lines=(),
        unit_bus={"G1": "A", "G2": "A"},
        hourly_demand_mw={"A": load},
        slack_bus="A",
        base_mva=100,
        topology_source="explicit synthetic single-bus unit ramp test",
        demand_source=snapshot.forecast_source,
    )
    specs = {
        "G1": replace(
            specs["G1"], initial_on=False, initial_mw=0,
            initial_state_hours=10, min_mw=20,
            ramp_up_mw=20, ramp_down_mw=20,
            startup_ramp_mw=30, shutdown_ramp_mw=40,
        ),
        "G2": replace(specs["G2"], initial_mw=20),
    }
    result = joint_clear_day(snapshot, network, specs, "G1")
    assert any(h.unit_started["G1"] for h in result.hours)
    assert any(h.unit_stopped["G1"] for h in result.hours)
    assert any(h.accepted_by_unit["G1"] >= 50 for h in result.hours)
    physical = audit_dispatch(
        specs["G1"], [h.accepted_by_unit["G1"] for h in result.hours]
    )
    assert physical.feasible, physical.violations
    assert result.total_transition_cost >= specs["G1"].startup_cost
    assert all(
        h.accepted_by_unit["G1"] + h.accepted_by_unit["G2"]
        == pytest.approx(load[h.period - 1], abs=1e-5)
        for h in result.hours
    )


def test_peers_bid_multiplier_changes_cost_but_never_modifies_snapshot():
    snapshot, network, units = _model()
    result = joint_clear_day(
        snapshot, network, units, "G1", peer_bid_multiplier=1.1
    )
    assert result.hours[0].nodal_prices["B"] == pytest.approx(99)
    assert snapshot.bids["G2"][0].segments[0].price == 90


def test_candidate_hourly_bid_must_obey_same_curve_pmss_rule():
    snapshot, network, units = _model()
    different = (
        PeriodBid(1, 12, (BidSegment(0, 100, 60),)),
        PeriodBid(13, 24, (BidSegment(0, 100, 80),)),
    )
    with pytest.raises(ValueError, match="same-curve"):
        joint_clear_day(
            snapshot, network, units, "G1",
            candidate_plan=different,
        )


def test_initial_state_and_closing_mode_handled_explicitly():
    snapshot, network, units = _model()
    with pytest.raises(ValueError, match="terminal_mode"):
        joint_clear_day(snapshot, network, units, "G1", terminal_mode="unknown")
    with pytest.raises(ValueError, match="safe study limit"):
        joint_clear_day(snapshot, network, units, "G1", demand_multiplier=2.1)
