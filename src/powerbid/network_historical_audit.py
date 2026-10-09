"""Strict historical PMSS electrical balance / network-model diagnostic.

Only original, already-observed DA results are accepted. All errors describe
same-day historical consistency, NOT a newly submitted bid, future forecast,
physical AC validation, or complete PMSS clearing reproduction.

This audit intentionally reports BOTH possible global branch-flow signs to
make the convention observable. It does not silently flip flows or correct
measured data to force an apparent perfect nodal balance.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any

from powerbid.network_dispatch import DcNetwork
from powerbid.pmss_diagnostics import series24


@dataclass(frozen=True, slots=True)
class GridAuditHour:
    period: int
    observed_generation_mw: float | None
    day_ahead_load_mw: float
    system_generation_minus_load_mw: float | None
    observed_bus_balance_mae_mw: float | None
    observed_bus_balance_reverse_mae_mw: float | None
    max_observed_bus_balance_error_mw: float | None
    observed_line_over_nameplate_count: int
    observed_line_count: int
    complete_observation: bool
    modeled_unit_mae_mw: float | None
    modeled_nodal_price_mae: float | None
    modeled_abs_flow_mae_mw: float | None


@dataclass(frozen=True, slots=True)
class GridAuditItem:
    element_id: str
    mae: float
    points: int


@dataclass(frozen=True, slots=True)
class PMSSHistoricalGridAudit:
    case_date: str
    market_type: str
    node_count: int
    line_count: int
    unit_count: int
    balanced_hour_count: int
    total_day_ahead_energy_mwh: float
    generation_load_mae_mw: float | None
    bus_balance_mae_mw: float | None
    reverse_flow_bus_balance_mae_mw: float | None
    modeled_unit_mae_mw: float | None
    modeled_nodal_price_mae: float | None
    modeled_abs_flow_mae_mw: float | None
    observed_line_over_nameplate_hours: int
    observed_missing_hours: int
    hours: tuple[GridAuditHour, ...]
    worst_bus_balance: tuple[GridAuditItem, ...]
    worst_nodal_model_prices: tuple[GridAuditItem, ...]
    worst_line_model_flows: tuple[GridAuditItem, ...]
    disclaimer: str = (
        "One already-cleared DA date only; uncalibrated PMSS/physical-model "
        "comparison, NOT held-out accuracy, PMSS counterfactual, or "
        "recommendation to submit a bid"
    )


def _source_id(row: Mapping[str, Any]) -> str:
    return str(row.get("element_id") or row.get("elementId") or row.get("unit_id") or "")


def _read_rows(
    observed: Mapping[str, Any],
    name: str,
    expected: set[str],
) -> dict[str, Mapping[str, Any]]:
    raw = observed.get(name)
    if not isinstance(raw, list) or len(raw) != len(expected):
        raise ValueError(f"PMSS {name}: required ID set is incomplete")
    rows = {}
    for row in raw:
        if not isinstance(row, Mapping):
            raise ValueError(f"PMSS {name}: invalid result object")
        ident = _source_id(row)
        if not ident or ident in rows or (
            row.get("market_type") or row.get("marketTypeAtom")
        ) != "DA":
            raise ValueError(f"PMSS {name}: duplicate ID or non-DA result")
        rows[ident] = row
    if set(rows) != expected:
        raise ValueError(f"PMSS {name}: historical IDs differ from verified topology")
    return rows


def _mean_abs(values: Sequence[float]) -> float | None:
    return sum(abs(value) for value in values) / len(values) if values else None


def _worst(
    errors: Mapping[str, list[float]],
    *,
    limit: int = 8,
) -> tuple[GridAuditItem, ...]:
    rows = [
        GridAuditItem(element_id=ident, mae=sum(vals) / len(vals), points=len(vals))
        for ident, vals in errors.items() if vals
    ]
    rows.sort(key=lambda item: (-item.mae, item.element_id))
    return tuple(rows[:limit])


def audit_pmss_historical_grid(
    network: DcNetwork,
    observed: Mapping[str, Any],
    *,
    case_date: str,
    modeled_hours: Sequence[Any] | None = None,
) -> PMSSHistoricalGridAudit:
    """Compare observed generator MW, bus MW and line MW per hour.

    modeled_hours, if present, must be the exact original-offer neutral
    NetworkBidResult.scenarios[0].hours (not a proposed-bid outcome). The
    caller must validate that provenance before providing it.
    """
    if observed.get("marketTypeAtom") != "DA" or observed.get("periodNum") != 24:
        raise ValueError("Expected the matching 24h PMSS day-ahead historical result")
    if not isinstance(case_date, str) or not case_date.strip():
        raise ValueError("Historical case date is required")
    if modeled_hours is not None and (
        len(modeled_hours) != 24
        or any(getattr(hour, "period", None) != idx for idx, hour in enumerate(modeled_hours, 1))
    ):
        raise ValueError("Model hours must be strictly ordered 1..24")
    units = _read_rows(observed, "unitResults", set(network.unit_bus))
    nodes = _read_rows(observed, "nodalPrices", set(network.buses))
    lines = _read_rows(observed, "branchFlows", {line.line_id for line in network.lines})
    power = {unit: series24(row, "accepted_mw", "power") for unit, row in units.items()}
    lmp = {bus: series24(row, "lmp", "powerFlow") for bus, row in nodes.items()}
    flow = {line: series24(row, "flow_mw", "powerFlow") for line, row in lines.items()}
    injection_units: dict[str, list[str]] = {bus: [] for bus in network.buses}
    for unit, bus in network.unit_bus.items():
        injection_units[bus].append(unit)
    from_bus: dict[str, list[str]] = {bus: [] for bus in network.buses}
    to_bus: dict[str, list[str]] = {bus: [] for bus in network.buses}
    for line in network.lines:
        from_bus[line.from_bus].append(line.line_id)
        to_bus[line.to_bus].append(line.line_id)
    upper = {line.line_id: line.limit_mw for line in network.lines}
    hours = []
    all_balance: list[float] = []
    all_reverse: list[float] = []
    all_system: list[float] = []
    modeled_units: list[float] = []
    modeled_nodes: list[float] = []
    modeled_flows: list[float] = []
    balance_by_bus: dict[str, list[float]] = {bus: [] for bus in network.buses}
    node_by_bus: dict[str, list[float]] = {bus: [] for bus in network.buses}
    flow_by_line: dict[str, list[float]] = {line: [] for line in lines}
    observed_over_limit = 0
    missing_hours = 0
    for idx in range(24):
        load = sum(series[idx] for series in network.hourly_demand_mw.values())
        # A partial observed hour is NOT silently assumed to be zero output.
        complete = (
            all(series[idx] is not None for series in power.values())
            and all(series[idx] is not None for series in flow.values())
            and all(series[idx] is not None for series in lmp.values())
        )
        generation = (
            sum(series[idx] for series in power.values())
            if all(series[idx] is not None for series in power.values()) else None
        )
        imbalance = generation - load if generation is not None else None
        if imbalance is not None:
            all_system.append(imbalance)
        err, reverse = [], []
        if complete:
            for bus in network.buses:
                gen = sum(power[unit][idx] for unit in injection_units[bus])
                net_flow = (
                    sum(flow[line][idx] for line in from_bus[bus])
                    - sum(flow[line][idx] for line in to_bus[bus])
                )
                injection = gen - network.hourly_demand_mw[bus][idx]
                residual = injection - net_flow
                inverse_residual = injection + net_flow
                err.append(abs(residual))
                reverse.append(abs(inverse_residual))
                balance_by_bus[bus].append(abs(residual))
            all_balance.extend(err)
            all_reverse.extend(reverse)
        else:
            missing_hours += 1
        over = sum(
            value[idx] is not None and abs(value[idx]) > upper[line] + 1e-6
            for line, value in flow.items()
        )
        observed_over_limit += over
        unit_errors, node_errors, line_errors = [], [], []
        if modeled_hours is not None:
            modeled = modeled_hours[idx]
            for unit, values in power.items():
                actual = values[idx]
                if actual is not None:
                    change = abs(modeled.dispatched_mw - actual) if False else None
                    # NetworkHour only contains the TARGET dispatch MW, not
                    # all-unit awards. Compute all-unit MAE only when a
                    # full dispatch mapping is explicitly supplied.
                    if change is not None:
                        unit_errors.append(change)
                        modeled_units.append(change)
            for bus, values in lmp.items():
                actual = values[idx]
                if actual is not None:
                    e = abs(modeled.nodal_prices[bus] - actual)
                    node_errors.append(e)
                    modeled_nodes.append(e)
                    node_by_bus[bus].append(e)
            for line, values in flow.items():
                actual = values[idx]
                if actual is not None:
                    e = abs(abs(modeled.branch_flows_mw[line]) - abs(actual))
                    line_errors.append(e)
                    modeled_flows.append(e)
                    flow_by_line[line].append(e)
        hours.append(GridAuditHour(
            period=idx + 1,
            observed_generation_mw=generation,
            day_ahead_load_mw=load,
            system_generation_minus_load_mw=imbalance,
            observed_bus_balance_mae_mw=_mean_abs(err),
            observed_bus_balance_reverse_mae_mw=_mean_abs(reverse),
            max_observed_bus_balance_error_mw=max(err) if err else None,
            observed_line_over_nameplate_count=over,
            observed_line_count=sum(series[idx] is not None for series in flow.values()),
            complete_observation=complete,
            modeled_unit_mae_mw=_mean_abs(unit_errors),
            modeled_nodal_price_mae=_mean_abs(node_errors),
            modeled_abs_flow_mae_mw=_mean_abs(line_errors),
        ))
    return PMSSHistoricalGridAudit(
        case_date=case_date, market_type="DA",
        node_count=len(network.buses), line_count=len(network.lines),
        unit_count=len(network.unit_bus),
        balanced_hour_count=24-missing_hours,
        total_day_ahead_energy_mwh=sum(
            sum(row) for row in network.hourly_demand_mw.values()
        ),
        generation_load_mae_mw=_mean_abs(all_system),
        bus_balance_mae_mw=_mean_abs(all_balance),
        reverse_flow_bus_balance_mae_mw=_mean_abs(all_reverse),
        modeled_unit_mae_mw=_mean_abs(modeled_units),
        modeled_nodal_price_mae=_mean_abs(modeled_nodes),
        modeled_abs_flow_mae_mw=_mean_abs(modeled_flows),
        observed_line_over_nameplate_hours=observed_over_limit,
        observed_missing_hours=missing_hours,
        hours=tuple(hours),
        worst_bus_balance=_worst(balance_by_bus),
        worst_nodal_model_prices=_worst(node_by_bus),
        worst_line_model_flows=_worst(flow_by_line),
    )
