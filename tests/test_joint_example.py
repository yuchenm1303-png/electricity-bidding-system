"""Run all three explicitly synthetic uploaded documents through the 24h MILP."""
import json
from pathlib import Path

import pytest

from powerbid.joint_strategy import compare_joint_bids
from powerbid.network_dispatch import network_from_dict
from powerbid.pmss_integration import snapshot_from_pmss
from powerbid.strategy_lab import BidPolicy, DemandStress
from powerbid.unit_commitment import ThermalConstraints

EXAMPLES = Path(__file__).resolve().parents[1] / "data" / "examples"


def _load(path):
    return json.loads((EXAMPLES / path).read_text("utf-8"))


def test_bundled_joint_example_is_explicitly_synthetic_and_solves_offline():
    pmss = _load("synthetic_dc_pmss.json")
    topo = _load("synthetic_dc_network.json")
    specs = _load("synthetic_joint_technical.json")
    assert pmss.get("syntheticExample")
    assert "synthetic" in pmss["forecastSource"].lower()
    assert "NOT PMSS" in topo["topologySource"]
    snapshot = snapshot_from_pmss(
        unit_tree=pmss["unitTree"],
        unit_bids=pmss["unitBids"],
        market_system=pmss["marketSystem"],
        demand_forecast_mw=pmss["demandForecastMw"],
        forecast_source=pmss["forecastSource"],
    )
    network = network_from_dict(topo)
    physical = {id_: ThermalConstraints(**raw) for id_, raw in specs.items()}
    result = compare_joint_bids(
        snapshot, network, physical, "G1",
        policies=(BidPolicy("cost"), BidPolicy("markup20", markup=20)),
        scenarios=(DemandStress("neutral"),),
    )
    assert result.baseline.scenarios[0].market.hours[0].nodal_prices["A"] == pytest.approx(
        60
    )
    assert result.baseline.scenarios[0].market.hours[0].nodal_prices["B"] == pytest.approx(
        90
    )
    assert result.recommended in result.ranked
    assert all(result.scenarios[0].market.pricing_method.startswith("fixed-commitment")
               for result in result.ranked)
