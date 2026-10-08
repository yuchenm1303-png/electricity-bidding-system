"""End-to-end bundled DC example is visibly synthetic and runnable offline."""
import json
from pathlib import Path

import pytest

from powerbid.network_dispatch import network_from_dict
from powerbid.network_strategy import compare_network_policies, verify_network_inputs
from powerbid.pmss_integration import snapshot_from_pmss
from powerbid.strategy_lab import DemandStress
from powerbid.unit_commitment import ThermalConstraints

ROOT = Path(__file__).resolve().parents[1] / "data" / "examples"


def _load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_example_is_not_real_pmss_and_always_matches_nodal_load():
    case = _load("synthetic_dc_pmss.json")
    grid = _load("synthetic_dc_network.json")
    assert case["syntheticExample"] is True
    assert "synthetic" in case["forecastSource"].lower()
    assert "NOT PMSS" in grid["topologySource"]
    snapshot = snapshot_from_pmss(
        unit_tree=case["unitTree"],
        unit_bids=case["unitBids"],
        market_system=case["marketSystem"],
        demand_forecast_mw=case["demandForecastMw"],
        forecast_source=case["forecastSource"],
    )
    network = network_from_dict(grid)
    verify_network_inputs(snapshot, network, "G1")
    assert len(network.buses) == 2
    assert len(network.lines) == 1


def test_example_replays_congested_24h_and_physical_screen():
    case = _load("synthetic_dc_pmss.json")
    network = network_from_dict(_load("synthetic_dc_network.json"))
    physical = ThermalConstraints(**_load("synthetic_dc_g1_physical.json"))
    snapshot = snapshot_from_pmss(
        unit_tree=case["unitTree"],
        unit_bids=case["unitBids"],
        market_system=case["marketSystem"],
        demand_forecast_mw=case["demandForecastMw"],
        forecast_source=case["forecastSource"],
    )
    result = compare_network_policies(
        snapshot, network, "G1",
        scenarios=(DemandStress("normal"),), physical=physical,
    )
    original = result.baseline.scenarios[0]
    assert len(original.hours) == 24
    assert original.hours[0].dispatched_mw == pytest.approx(30.0)
    assert original.hours[0].target_lmp == pytest.approx(60.0)
    assert original.hours[0].branch_flows_mw["LINE-AB"] == pytest.approx(30.0)
    assert original.hours[0].nodal_prices["B"] == pytest.approx(90.0)
    assert result.recommended.physically_feasible is True
