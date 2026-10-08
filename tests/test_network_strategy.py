"""Validate lossless DC nodal clearing and historical feedback separation."""
from dataclasses import replace

import pytest
from test_strategy_lab import _snapshot

from powerbid.network_dispatch import (
    DcInfeasibleError,
    DcLine,
    DcNetwork,
    DcOffer,
    dc_clear_hour,
    network_from_dict,
)
from powerbid.network_feedback import compare_dc_baseline_to_pmss
from powerbid.network_strategy import (
    compare_network_policies,
    evaluate_network_plan,
    verify_network_inputs,
)
from powerbid.strategy_lab import BidPolicy, DemandStress


def _network(*, thermal_limit=30.0, loads=160.0, source="explicit synthetic demand fixture"):
    return DcNetwork(
        buses=("A", "B"),
        lines=(DcLine("line-AB", "A", "B", 0.1, thermal_limit),),
        unit_bus={"G1": "A", "G2": "B"},
        hourly_demand_mw={"A": (0.0,) * 24, "B": (loads,) * 24},
        slack_bus="A",
        base_mva=100.0,
        topology_source="verified synthetic test topology",
        demand_source=source,
    )


def test_congested_line_causes_distinct_nodal_prices_and_local_dispatch():
    network = _network(loads=80)
    market = dc_clear_hour(
        network, (DcOffer("G1", 1, 100.0, 10.0), DcOffer("G2", 1, 100.0, 100.0)), 1
    )
    assert market.accepted_by_unit["G1"] == pytest.approx(30.0)
    assert market.accepted_by_unit["G2"] == pytest.approx(50.0)
    assert market.line_flows_mw["line-AB"] == pytest.approx(30.0)
    assert market.nodal_prices["A"] == pytest.approx(10.0)
    assert market.nodal_prices["B"] == pytest.approx(100.0)
    assert market.clearing_offer_cost == pytest.approx(5300.0)


def test_uncongested_line_results_in_identical_nodal_prices():
    network = _network(thermal_limit=120, loads=80)
    market = dc_clear_hour(
        network, (DcOffer("G1", 1, 100.0, 10.0), DcOffer("G2", 1, 100.0, 100.0)), 1
    )
    assert market.accepted_by_unit["G1"] == pytest.approx(80.0)
    assert market.accepted_by_unit["G2"] == pytest.approx(0.0)
    assert market.nodal_prices["A"] == pytest.approx(10)
    assert market.nodal_prices["B"] == pytest.approx(10)


def test_line_capacity_can_make_market_infeasible_despite_total_generating_capacity():
    network = _network(loads=160, thermal_limit=5)
    with pytest.raises(DcInfeasibleError, match="cannot meet demand"):
        dc_clear_hour(
            network, (DcOffer("G1", 1, 100, 10), DcOffer("G2", 1, 150, 90)), 1
        )


def test_network_rejects_disconnected_buses_and_unverified_node():
    network = _network()
    with pytest.raises(ValueError, match="Disconnected"):
        replace(
            network, buses=("A", "B", "C"),
            hourly_demand_mw={**network.hourly_demand_mw, "C": (0.0,) * 24},
        )
    with pytest.raises(ValueError, match="unknown"):
        replace(network, unit_bus={"G1": "NO_NODE", "G2": "B"})
    with pytest.raises(ValueError, match="reactance"):
        DcLine("bad", "A", "B", 0.0, 50)


def test_network_strict_loader_does_not_guess_ids_or_allow_extras():
    raw = {
        "buses": ["A", "B"],
        "lines": [{
            "lineId": "line-AB", "fromBus": "A", "toBus": "B",
            "reactancePu": 0.1, "limitMw": 30.0,
        }],
        "unitBus": {"G1": "A", "G2": "B"},
        "hourlyDemandMw": {"A": [0] * 24, "B": [160] * 24},
        "slackBus": "A", "baseMva": 100.0,
        "topologySource": "verified synthetic test topology",
        "demandSource": "explicit synthetic demand fixture",
    }
    network = network_from_dict(raw)
    assert network.hourly_demand_mw["B"][0] == 160
    with pytest.raises(ValueError, match="schema keys"):
        network_from_dict(raw | {"sessionToken": "never-accept"})
    with pytest.raises(ValueError, match="line needs"):
        network_from_dict(raw | {"lines": [{"lineId": "line-AB"}]})


def test_snapshot_network_nodal_load_match_mandatory():
    snapshot = _snapshot()
    network = _network()
    verify_network_inputs(snapshot, network, "G1")
    with pytest.raises(ValueError, match="disagrees"):
        verify_network_inputs(snapshot, _network(loads=159), "G1")
    with pytest.raises(ValueError, match="source"):
        verify_network_inputs(
            snapshot, replace(network, demand_source="different assumption"), "G1"
        )


def test_network_strategy_uses_nodal_price_and_24h_market_reclearing():
    snapshot = _snapshot()
    network = _network()
    result = compare_network_policies(
        snapshot, network, "G1",
        policies=(BidPolicy("cost"), BidPolicy("high margin", markup=40)),
        scenarios=(DemandStress("normal"),),
    )
    assert 1 <= result.evaluated <= 3
    baseline = result.baseline
    assert baseline.scenarios[0].hours[0].dispatched_mw == pytest.approx(30)
    assert baseline.scenarios[0].hours[0].target_lmp == pytest.approx(60)
    assert baseline.scenarios[0].hours[0].branch_flows_mw["line-AB"] == pytest.approx(30)
    assert baseline.expected_margin == pytest.approx((60-50)*30*24)
    assert result.recommended in result.ranked


def test_network_stress_analysis_reacts_to_peer_bid_changes():
    snapshot = _snapshot()
    network = _network(thermal_limit=120)
    a = evaluate_network_plan(
        snapshot, network, "G1", "baseline", snapshot.bids["G1"],
        (DemandStress("normal"),),
    )
    b = evaluate_network_plan(
        snapshot, network, "G1", "baseline", snapshot.bids["G1"],
        (DemandStress("higher competitor", peer_price_factor=1.3),),
    )
    assert a.scenarios[0].hours[0].target_lmp <= b.scenarios[0].hours[0].target_lmp


def _pmss_from_model(baseline):
    hours = baseline.scenarios[0].hours
    return {
        "periodNum": 24, "marketTypeAtom": "DA",
        "unitResults": [{
            "unit_id": "G1", "market_type": "DA",
            "accepted_mw": [h.dispatched_mw for h in hours],
            "clearing_prices": [h.target_lmp for h in hours],
        }],
        "nodalPrices": [
            {"element_id": bus, "market_type": "DA",
             "lmp": [h.nodal_prices[bus] for h in hours]}
            for bus in ("A", "B")
        ],
        "branchFlows": [{
            "element_id": "line-AB", "market_type": "DA",
            "flow_mw": [-h.branch_flows_mw["line-AB"] for h in hours],
        }],
    }


def test_baseline_only_historical_comparison_has_zero_error_for_matching_fixture():
    snapshot, network = _snapshot(), _network()
    baseline = compare_network_policies(
        snapshot, network, "G1",
        policies=(BidPolicy("cost"),), scenarios=(DemandStress("normal"),)
    ).baseline
    data = _pmss_from_model(baseline)
    comparison = compare_dc_baseline_to_pmss(snapshot, network, baseline, "G1", data)
    assert comparison.target_dispatch_mae_mw == pytest.approx(0)
    assert comparison.target_price_mae == pytest.approx(0)
    assert comparison.nodal_price_mae == pytest.approx(0)
    assert comparison.line_absolute_flow_mae_mw == pytest.approx(0)
    assert comparison.observed_network_node_points == 48
    assert comparison.observed_line_flow_points == 24


def test_baseline_comparison_rejects_wrong_identity_or_new_strategy():
    snapshot, network = _snapshot(), _network()
    result = compare_network_policies(
        snapshot, network, "G1",
        policies=(BidPolicy("high margin", markup=40),),
        scenarios=(DemandStress("normal"),),
    )
    with pytest.raises(ValueError, match="original-bid"):
        compare_dc_baseline_to_pmss(
            snapshot, network, result.ranked[-1]
            if not result.ranked[-1].name.startswith("PMSS")
            else result.ranked[0],
            "G1", _pmss_from_model(result.baseline)
        ) if any(not x.name.startswith("PMSS") for x in result.ranked) else None
    data = _pmss_from_model(result.baseline)
    data["nodalPrices"][0]["element_id"] = "unknown"
    with pytest.raises(ValueError, match="node IDs"):
        compare_dc_baseline_to_pmss(snapshot, network, result.baseline, "G1", data)


def test_missing_history_points_not_zero_filled():
    snapshot, network = _snapshot(), _network()
    baseline = compare_network_policies(
        snapshot, network, "G1",
        policies=(BidPolicy("cost"),), scenarios=(DemandStress("normal"),)
    ).baseline
    data = _pmss_from_model(baseline)
    data["unitResults"][0]["accepted_mw"][10] = None
    data["branchFlows"][0]["flow_mw"][2] = None
    compared = compare_dc_baseline_to_pmss(snapshot, network, baseline, "G1", data)
    assert compared.observed_accepted_points == 23
    assert compared.observed_line_flow_points == 23


def test_optional_physical_constraints_screen_network_market_outcomes():
    from powerbid.unit_commitment import ThermalConstraints

    snapshot, network = _snapshot(), _network()
    physical = ThermalConstraints(
        unit_id="G1", min_mw=15, max_mw=100, ramp_up_mw=100,
        ramp_down_mw=100, startup_ramp_mw=100, shutdown_ramp_mw=100,
        min_up_hours=1, min_down_hours=1, startup_cost=50, shutdown_cost=0,
        initial_on=True, initial_mw=30, initial_state_hours=10,
    )
    result = compare_network_policies(
        snapshot, network, "G1",
        policies=(BidPolicy("cost"), BidPolicy("high", markup=200)),
        scenarios=(DemandStress("normal"),),
        physical=physical,
    )
    assert result.baseline.physically_feasible is True
    assert result.recommended.physically_feasible is True
    assert any(item.physically_feasible is False for item in result.ranked)


def test_if_no_physically_credible_network_plan_then_no_recommendation():
    from powerbid.unit_commitment import ThermalConstraints

    snapshot, network = _snapshot(), _network()
    impossible = ThermalConstraints(
        unit_id="G1", min_mw=99, max_mw=100, ramp_up_mw=100,
        ramp_down_mw=100, startup_ramp_mw=100, shutdown_ramp_mw=100,
        min_up_hours=1, min_down_hours=1, startup_cost=50, shutdown_cost=0,
        initial_on=True, initial_mw=100, initial_state_hours=10,
    )
    with pytest.raises(ValueError, match="No candidate passed"):
        compare_network_policies(
            snapshot, network, "G1", policies=(BidPolicy("cost"),),
            scenarios=(DemandStress("normal"),),
            physical=impossible,
        )
