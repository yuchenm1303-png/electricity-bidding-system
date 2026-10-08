"""Whitelist-only export of the authorized PMSS network (no session data).

The private PMSS grid snapshot is read on the trusted server. Neither that
original file nor network identifiers from a class assignment belong in Git.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from powerbid.pmss_dc_network import parse_grid
from powerbid.pmss_integration import PMSSSnapshot


def sanitize_pmss_grid(
    original: Mapping[str, Any],
    *,
    snapshot: PMSSSnapshot,
) -> dict[str, Any]:
    if not isinstance(original, Mapping):
        raise ValueError("Expected an authorized PMSS network export")
    raw_nodes = original["nodes"]["datas"]
    raw_lines = original["lines"]["datas"]
    raw_units = original["units"]["datas"]
    raw_loads = original["loads"]["data"]["datas"]
    if not all(isinstance(rows, list) for rows in (raw_nodes, raw_lines, raw_units, raw_loads)):
        raise ValueError("Invalid PMSS grid tables")

    name_by_id: dict[str, str] = {}
    for node in raw_nodes:
        key, name = str(node["id"]), str(node["name"])
        if key in name_by_id or name in name_by_id.values():
            raise ValueError("Duplicated bus in PMSS grid")
        name_by_id[key] = name

    by_load: dict[str, dict[str, Any]] = {}
    summary: dict[str, Any] | None = None
    for row in raw_loads:
        name = str(row["elementName"])
        if name == "统调负荷":
            if summary is not None:
                raise ValueError("More than one system load total")
            summary = row
            continue
        if name in by_load:
            raise ValueError("Duplicate PMSS bus load")
        by_load[name] = row
    if set(by_load) != set(name_by_id.values()):
        raise ValueError("PMSS nodal DA load is missing buses or includes extras")
    if summary is None:
        raise ValueError("Missing PMSS system DA load for reconciliation")

    buses = []
    for name in name_by_id.values():
        da = by_load[name]["da"]
        buses.append({
            "bus": name,
            "loadMw": [da[f"t{hour:02d}"] for hour in range(1, 25)],
        })
    lines = []
    for line in raw_lines:
        start, end = str(line["bgnNodeId"]), str(line["endNodeId"])
        if start not in name_by_id or end not in name_by_id:
            raise ValueError("Line references nonexistent PMSS bus")
        # Original id/cimId/netId never exported; public-facing line name
        # must be distinct so topology can be independently audited.
        lines.append({
            "lineId": str(line["name"]),
            "fromBus": name_by_id[start],
            "toBus": name_by_id[end],
            "x": line["x"],
            "limitMw": line["ratedMw"],
        })

    unit_buses = {}
    for row in raw_units:
        unit_id = str(row["id"])
        bus_id = str(row["nodeId"])
        if unit_id in unit_buses or bus_id not in name_by_id:
            raise ValueError("Invalid unit-bus mapping")
        unit_buses[unit_id] = name_by_id[bus_id]
    cleaned = {
        "schema": "powerbid.pmss.dc-grid.v1",
        "provenance": (
            "PMSS authorized 39-bus operating grid: read-only node, line, "
            "unit-to-node and historical DA load inputs. DC approximation."
        ),
        "buses": buses,
        "lines": lines,
        "unitBuses": unit_buses,
    }
    network = parse_grid(cleaned, snapshot=snapshot)
    for hour in range(24):
        expected = float(summary["da"][f"t{hour+1:02d}"])
        actual = sum(v[hour] for v in network.hourly_loads_mw.values())
        if abs(expected - actual) > 0.1:
            raise ValueError(f"Network hour {hour+1} load differs from PMSS total")
    return cleaned
