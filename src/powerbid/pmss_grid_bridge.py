"""Trusted-host PMSS network bridge for the EXISTING DC bidding/strategy engine.

Only named, read-only PMSS grid fields are allowlisted. The private original
network JSON is never copied to Git or a public endpoint.

The PMSS source provides per-unit relative branch x, all transformer ratios
are 1, but does not certify a physical system baseMVA. Use baseMva=1 solely
as a computational angle normalization: in this lossless DC model a common
base scales theta but *cancels from bus injections, flows and dual prices*.
Do not interpret the resulting theta as physical radians.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

from powerbid.network_dispatch import network_from_dict
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_integration import PMSSSnapshot


def sanitize_pmss_network(
    private_grid: Mapping[str, Any], *, snapshot: PMSSSnapshot,
) -> dict[str, Any]:
    if not isinstance(private_grid, Mapping):
        raise ValueError("PMSS network must come from an authorized read-only export")
    try:
        nodes = private_grid["nodes"]["datas"]
        lines = private_grid["lines"]["datas"]
        units = private_grid["units"]["datas"]
        loads = private_grid["loads"]["data"]["datas"]
    except (TypeError, KeyError) as exc:
        raise ValueError("Incomplete PMSS network model tables") from exc
    if not all(isinstance(v, list) for v in (nodes, lines, units, loads)):
        raise ValueError("Invalid PMSS table shape")
    if not nodes or not lines or not units:
        raise ValueError("PMSS network lacks nodes, lines or generation")
    bus_names: dict[str, str] = {}
    for item in nodes:
        ident = str(item["id"])
        name = str(item["name"])
        if not ident or not name or ident in bus_names or name in bus_names.values():
            raise ValueError("Invalid duplicate bus")
        bus_names[ident] = name
    demand: dict[str, list[float]] = {}
    total_row = None
    for row in loads:
        ident = str(row["elementId"])
        if row.get("elementName") == "统调负荷":
            if total_row is not None:
                raise ValueError("Duplicate PMSS system load summary")
            total_row = row
            continue
        if ident in demand:
            raise ValueError("Duplicate PMSS bus load")
        if ident not in bus_names or row.get("elementName") != bus_names[ident]:
            raise ValueError("PMSS node load ID or name disagrees with grid")
        da = row["da"]
        demand[ident] = [float(da[f"t{i:02d}"]) for i in range(1, 25)]
    if set(demand) != set(bus_names) or total_row is None:
        raise ValueError("Missing Bus loads or PMSS system load summary")
    for period in range(24):
        total = sum(data[period] for data in demand.values())
        expected = float(total_row["da"][f"t{period+1:02d}"])
        if not isfinite(total) or abs(total - expected) > 0.1:
            raise ValueError(f"PMSS nodal/system load mismatch in hour {period+1}")
    model_lines: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in lines:
        ident = str(item["id"])
        a, b = str(item["bgnNodeId"]), str(item["endNodeId"])
        if ident in seen or not ident or a not in bus_names or b not in bus_names:
            raise ValueError("Duplicate line or missing endpoint")
        if float(item["ratio"]) != 1.0:
            raise ValueError("Non-unity PMSS transformer ratio needs separate model")
        seen.add(ident)
        model_lines.append({
            "lineId": ident,
            "fromBus": a,
            "toBus": b,
            "reactancePu": item["x"],
            "limitMw": item["ratedMw"],
        })
    unit_bus: dict[str, str] = {}
    for item in units:
        ident, bus = str(item["id"]), str(item["nodeId"])
        if ident in unit_bus or bus not in bus_names:
            raise ValueError("Duplicated generator or missing verified bus")
        unit_bus[ident] = bus
    network = {
        "buses": list(bus_names),
        "lines": model_lines,
        "unitBus": unit_bus,
        "hourlyDemandMw": demand,
        "slackBus": next(iter(bus_names)),
        "baseMva": 1.0,
        "topologySource": (
            "AUTHORIZED PMSS read-only network: original Bus/Line/Unit IDs, "
            "relative x and rated MW. baseMva=1 computational normalization "
            "ONLY (physical angle base not verified)."
        ),
        "demandSource": snapshot.forecast_source,
    }
    parsed = network_from_dict(network)
    verify_network_inputs(snapshot, parsed, snapshot.units[0].unit_id)
    return network
