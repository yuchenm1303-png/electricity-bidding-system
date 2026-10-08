"""Read-only 24h *linear DC network* market dispatch using actual PMSS grid inputs.

This is NOT PMSS's full clearing engine. It ignores binary commitment, ramping,
reserves, losses, reactive power and AC security. Branch x is used only for
*relative* DC network susceptances: an unknown common MVA base cancels out
of unconstrained bus-angle normalization and branch MW flows.

All topology must be explicitly provided; missing nodes, branches, unit
locations, hourly load, or branch thermal limits cause a hard error. No
heuristic line capacities or synthetic network is silently invented.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

from powerbid.pmss_integration import BidSegment, PMSSSnapshot, curve_for_period
from powerbid.pmss_strategy import validate_curve


@dataclass(frozen=True, slots=True)
class DCLine:
    line_id: str
    from_bus: str
    to_bus: str
    reactance: float
    limit_mw: float


@dataclass(frozen=True, slots=True)
class DCGrid:
    buses: tuple[str, ...]
    lines: tuple[DCLine, ...]
    hourly_loads_mw: dict[str, tuple[float, ...]]
    unit_buses: dict[str, str]
    provenance: str


@dataclass(frozen=True, slots=True)
class DCHour:
    period: int
    demand_mw: float
    target_mw: float
    target_lmp: float
    target_profit: float
    accepted_mw: dict[str, float]
    lmp_by_bus: dict[str, float]
    flows_mw: dict[str, float]
    congested_lines: tuple[str, ...]
    objective_bid_cost: float


@dataclass(frozen=True, slots=True)
class DCStudy:
    target_unit_id: str
    hours: tuple[DCHour, ...]
    total_profit: float
    total_accepted_mwh: float
    max_line_utilization: float
    hours_with_binding_lines: int
    study_type: str = "local DC-OPF counterfactual approximation, NOT PMSS clearing"


def _num(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label}: boolean is not numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: invalid numeric value") from exc
    if not isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{label}: expected finite {'positive ' if positive else ''}value")
    return result


def parse_grid(grid: Mapping[str, Any], *, snapshot: PMSSSnapshot | None = None) -> DCGrid:
    """Strict allowlisted grid schema populated from *read-only* PMSS network data."""
    if not isinstance(grid, Mapping):
        raise ValueError("PMSS grid must be an object")
    if grid.get("schema") != "powerbid.pmss.dc-grid.v1":
        raise ValueError("Unsupported PMSS network snapshot schema")
    provenance = grid.get("provenance")
    if not isinstance(provenance, str) or not provenance.strip():
        raise ValueError("Network topology must specify its source")
    nodes = grid.get("buses")
    branches = grid.get("lines")
    units = grid.get("unitBuses")
    if not isinstance(nodes, list) or not isinstance(branches, list) or not isinstance(units, dict):
        raise ValueError("Network requires buses, lines and unitBuses")
    if not 2 <= len(nodes) <= 120 or not 1 <= len(branches) <= 300:
        raise ValueError("Network size outside supported DC analysis range")
    buses: list[str] = []
    loads: dict[str, tuple[float, ...]] = {}
    for row in nodes:
        if not isinstance(row, Mapping) or set(row) != {"bus", "loadMw"}:
            raise ValueError("Each bus requires only bus and loadMw")
        bus = row["bus"]
        if not isinstance(bus, str) or not bus or len(bus) > 100 or bus in loads:
            raise ValueError("Invalid or duplicated bus identifier")
        values = row["loadMw"]
        if not isinstance(values, list) or len(values) != 24:
            raise ValueError(f"{bus}: expected 24 hourly DA loads")
        series = tuple(_num(v, f"{bus}.loadMw") for v in values)
        if any(v < 0 for v in series):
            raise ValueError(f"{bus}: negative nodal load unsupported")
        buses.append(bus)
        loads[bus] = series
    lines: list[DCLine] = []
    seen: set[str] = set()
    for row in branches:
        if not isinstance(row, Mapping) or set(row) != {
            "lineId", "fromBus", "toBus", "x", "limitMw"
        }:
            raise ValueError("Each line needs ID, endpoint buses, x, and limitMw")
        line_id = row["lineId"]
        a, b = row["fromBus"], row["toBus"]
        if not isinstance(line_id, str) or not line_id or line_id in seen or len(line_id)>100:
            raise ValueError("Duplicate or invalid line ID")
        if a not in loads or b not in loads or a == b:
            raise ValueError(f"{line_id}: unknown endpoint bus or self-loop")
        seen.add(line_id)
        lines.append(DCLine(
            line_id=line_id, from_bus=a, to_bus=b,
            reactance=_num(row["x"], f"{line_id}.x", positive=True),
            limit_mw=_num(row["limitMw"], f"{line_id}.limitMw", positive=True),
        ))
    if any(not isinstance(unit, str) or not isinstance(bus, str) or bus not in loads
           for unit, bus in units.items()):
        raise ValueError("Missing/invalid generator-to-bus mapping")
    if snapshot is not None:
        expected = {u.unit_id for u in snapshot.units}
        if set(units) != expected:
            raise ValueError("PMSS network unit-to-bus IDs differ from bids")
        for hour in range(24):
            total = sum(series[hour] for series in loads.values())
            target = snapshot.demand_forecast_mw[hour]
            if abs(total - target) > max(0.1, abs(target) * 1e-5):
                raise ValueError(
                    f"Network nodal load sum mismatches PMSS day-ahead load in hour {hour+1}"
                )
    adjacency: dict[str, set[str]] = {name: set() for name in buses}
    for line in lines:
        adjacency[line.from_bus].add(line.to_bus)
        adjacency[line.to_bus].add(line.from_bus)
    reachable = {buses[0]}
    stack = [buses[0]]
    while stack:
        for other in adjacency[stack.pop()]:
            if other not in reachable:
                reachable.add(other)
                stack.append(other)
    if len(reachable) != len(buses):
        raise ValueError("Disconnected network components require separate reference buses")
    return DCGrid(
        buses=tuple(buses), lines=tuple(lines),
        hourly_loads_mw=loads, unit_buses=dict(units), provenance=provenance,
    )


def solve_dc_hour(
    grid: DCGrid,
    snapshot: PMSSSnapshot,
    period: int,
    *,
    target_unit_id: str,
    target_segments: Sequence[BidSegment] | None = None,
) -> DCHour:
    """Solve generator segment LP plus nodal KCL and line DC flow equations.

    LP dual multipliers on bus power-balance equations are local *model* LMPs.
    Loads cannot disappear; an infeasible transmission/offer configuration is
    rejected, not converted into an invented 'optimal' solution.
    """
    if not 1 <= period <= 24:
        raise ValueError("period must be in 1..24")
    if target_unit_id not in grid.unit_buses:
        raise ValueError("Target generator lacks a bus")
    try:
        import numpy as np
        from scipy.optimize import linprog
        from scipy.sparse import lil_matrix
    except ImportError as exc:
        raise RuntimeError("DC network study requires optional dependency .[network]") from exc

    offers = []
    for unit in snapshot.units:
        blocks = (
            tuple(target_segments) if unit.unit_id == target_unit_id and target_segments is not None
            else curve_for_period(snapshot.bids[unit.unit_id], period)
        )
        validate_curve(blocks, snapshot.limits.max_segments)
        if blocks[-1].end_power > unit.capacity_mw + 1e-6:
            raise ValueError(f"{unit.unit_id}: bid blocks exceed verified adjustable capacity")
        for segment in blocks:
            offers.append((unit.unit_id, grid.unit_buses[unit.unit_id], segment))
    n_bus, n_line, n_seg = len(grid.buses), len(grid.lines), len(offers)
    bus_index = {name: index for index, name in enumerate(grid.buses)}
    # Variables: one nonnegative MW output per segment, one signed MW per
    # physical branch, and a free relative voltage-angle variable per bus.
    size = n_seg + n_line + n_bus
    def flow_index(i: int) -> int:
        return n_seg + i
    def theta_index(i: int) -> int:
        return n_seg + n_line + i

    objective = np.zeros(size, dtype=float)
    bounds: list[tuple[float | None, float | None]] = []
    for index, (_, _, segment) in enumerate(offers):
        objective[index] = segment.price
        bounds.append((0.0, segment.quantity_mw))
    bounds.extend((-line.limit_mw, line.limit_mw) for line in grid.lines)
    bounds.extend([(None, None)] * n_bus)
    bounds[theta_index(0)] = (0.0, 0.0)
    matrix = lil_matrix((n_bus+n_line, size), dtype=float)
    rhs = np.zeros(n_bus+n_line)
    for index, (_, bus, _) in enumerate(offers):
        matrix[bus_index[bus], index] += 1.0
    for index, line in enumerate(grid.lines):
        a, b = bus_index[line.from_bus], bus_index[line.to_bus]
        flow = flow_index(index)
        # Sending bus injection=-flow; receiving bus injection=+flow.
        matrix[a, flow] -= 1.0
        matrix[b, flow] += 1.0
        # branch flow = (theta_from-theta_to) / x.
        matrix[n_bus+index, flow] = 1.0
        matrix[n_bus+index, theta_index(a)] = -1.0/line.reactance
        matrix[n_bus+index, theta_index(b)] = 1.0/line.reactance
    for bus, index in bus_index.items():
        rhs[index] = grid.hourly_loads_mw[bus][period-1]
    result = linprog(
        objective, A_eq=matrix.tocsr(), b_eq=rhs, bounds=bounds, method="highs",
    )
    if not result.success or result.x is None:
        raise ValueError(
            f"DC network market infeasible at hour {period}; "
            "check real line limits, unit availability, and offer quantities"
        )
    accepted: dict[str, float] = {unit.unit_id: 0.0 for unit in snapshot.units}
    for idx, (unit_id, _, _) in enumerate(offers):
        accepted[unit_id] += max(0.0, float(result.x[idx]))
    lmps = {bus: float(result.eqlin.marginals[index]) for bus, index in bus_index.items()}
    flows = {
        line.line_id: float(result.x[flow_index(i)])
        for i, line in enumerate(grid.lines)
    }
    binding = tuple(
        line.line_id for line in grid.lines
        if abs(flows[line.line_id]) >= line.limit_mw - max(0.01, line.limit_mw * 1e-5)
    )
    target = snapshot.unit(target_unit_id)
    mw = accepted[target_unit_id]
    price = lmps[grid.unit_buses[target_unit_id]]
    return DCHour(
        period=period,
        demand_mw=sum(grid.hourly_loads_mw[bus][period-1] for bus in grid.buses),
        target_mw=mw, target_lmp=price,
        target_profit=(price-target.running_cost)*mw,
        accepted_mw=accepted, lmp_by_bus=lmps, flows_mw=flows,
        congested_lines=binding, objective_bid_cost=float(result.fun),
    )


def evaluate_dc_bid(
    grid: DCGrid,
    snapshot: PMSSSnapshot,
    target_unit_id: str,
    *,
    target_segments: Sequence[BidSegment] | None = None,
) -> DCStudy:
    if target_segments is not None:
        validate_curve(target_segments, snapshot.limits.max_segments)
        if not snapshot.limits.same_curve:
            raise ValueError("Same bid curve is required for all 24 periods")
    hours = tuple(
        solve_dc_hour(
            grid, snapshot, period,
            target_unit_id=target_unit_id, target_segments=target_segments,
        )
        for period in range(1, 25)
    )
    return DCStudy(
        target_unit_id=target_unit_id,
        hours=hours,
        total_profit=sum(h.target_profit for h in hours),
        total_accepted_mwh=sum(h.target_mw for h in hours),
        max_line_utilization=max(
            abs(h.flows_mw[line.line_id]) / line.limit_mw
            for h in hours for line in grid.lines
        ),
        hours_with_binding_lines=sum(bool(h.congested_lines) for h in hours),
    )
