import json
from pathlib import Path

import pytest

from powerbid.network_dispatch import network_from_dict
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_grid_bridge import sanitize_pmss_network
from powerbid.pmss_integration import snapshot_from_pmss

EXAMPLE = Path(__file__).resolve().parents[1] / "data/examples/synthetic_dc_pmss.json"


def _market_and_private_grid():
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    snapshot = snapshot_from_pmss(
        unit_tree=example["unitTree"],
        unit_bids=example["unitBids"],
        market_system=example["marketSystem"],
        demand_forecast_mw=example["demandForecastMw"],
        forecast_source=example["forecastSource"],
    )
    load = list(snapshot.demand_forecast_mw)
    def hourly(value):
        return {f"t{i:02d}": item for i, item in enumerate(value, 1)}
    private = {
        "nodes": {"datas": [
            {"id": "A", "name": "BusA", "cookie": "discarded"},
            {"id": "B", "name": "BusB", "cookie": "discarded"},
        ]},
        "lines": {"datas": [{
            "id": "LineAB", "bgnNodeId": "A", "endNodeId": "B",
            "ratio": 1, "x": 0.1, "ratedMw": 30,
            "netId": "private-historical-course-id",
        }]},
        "units": {"datas": [
            {"id": "G1", "nodeId": "A"},
            {"id": "G2", "nodeId": "B"},
        ]},
        "loads": {"data": {"datas": [
            {"elementId": "total", "elementName": "统调负荷", "da": hourly(load)},
            {"elementId": "A", "elementName": "BusA", "da": hourly([0] * 24)},
            {"elementId": "B", "elementName": "BusB", "da": hourly(load)},
        ]}},
    }
    return snapshot, private


def test_pmss_bridge_whitelists_sources_and_uses_existing_dc_engine():
    snapshot, original = _market_and_private_grid()
    sanitized = sanitize_pmss_network(original, snapshot=snapshot)
    dc = network_from_dict(sanitized)
    verify_network_inputs(snapshot, dc, "G1")
    assert dc.buses == ("A", "B")
    assert dc.unit_bus == {"G1": "A", "G2": "B"}
    assert dc.lines[0].limit_mw == 30
    assert dc.base_mva == 1
    assert "normalization" in dc.topology_source
    assert "cookie" not in json.dumps(sanitized)
    assert "private-historical-course-id" not in json.dumps(sanitized)


def test_pmss_bridge_rejects_nonunity_transformer_and_missing_load_bus():
    snapshot, original = _market_and_private_grid()
    original["lines"]["datas"][0]["ratio"] = 1.1
    with pytest.raises(ValueError, match="Non-unity"):
        sanitize_pmss_network(original, snapshot=snapshot)
    snapshot, original = _market_and_private_grid()
    original["loads"]["data"]["datas"].pop()
    with pytest.raises(ValueError, match="Missing Bus"):
        sanitize_pmss_network(original, snapshot=snapshot)


def test_pmss_bridge_rejects_system_load_disagreement():
    snapshot, original = _market_and_private_grid()
    original["loads"]["data"]["datas"][1]["da"]["t01"] = 5
    with pytest.raises(ValueError, match="node/system|nodal/system"):
        sanitize_pmss_network(original, snapshot=snapshot)


@pytest.mark.parametrize("name,value", [
    ("x", "0.1"),
    ("x", True),
    ("x", 0),
    ("ratedMw", "30"),
    ("ratedMw", float("inf")),
    ("ratio", True),
])
def test_pmss_grid_rejects_invalid_physical_parameter_units(name, value):
    snapshot, original = _market_and_private_grid()
    original["lines"]["datas"][0][name] = value
    with pytest.raises(ValueError, match="physical|positive"):
        sanitize_pmss_network(original, snapshot=snapshot)


def test_pmss_grid_rejects_explicit_ohm_reactance_without_conversion():
    snapshot, original = _market_and_private_grid()
    original["lines"]["datas"][0]["xUnit"] = "ohm"
    with pytest.raises(ValueError, match="reactance unit"):
        sanitize_pmss_network(original, snapshot=snapshot)


def test_pmss_grid_rejects_boolean_bus_load():
    snapshot, original = _market_and_private_grid()
    original["loads"]["data"]["datas"][1]["da"]["t01"] = True
    with pytest.raises(ValueError, match="nodal MW"):
        sanitize_pmss_network(original, snapshot=snapshot)
