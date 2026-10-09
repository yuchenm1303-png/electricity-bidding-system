"""Read-only counterfactual diagnostic: fixed *observed* PMSS injections in DC grid.

Crucial separation: keeping the actual dispatch fixed removes generator
dispatch / bid-selection differences from the flow comparison. Any remaining
difference with observed branch MW may reflect topology/branch assumptions,
AC physics, PSTs, losses, meters, or different PMSS reporting conventions.
It does NOT prove which of those caused the discrepancy.

No network requests, no PMSS writes, no optimization of historical data,
and no fabrication of missed dispatch. If injection fails to sum to load,
the hour is skipped rather than forcing a fake slack generator.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from math import isfinite, sqrt
from typing import Any

from powerbid.network_dispatch import DcNetwork
from powerbid.pmss_diagnostics import series24


@dataclass(frozen=True, slots=True)
class FixedInjectionHour:
    period: int
    status: str
    generation_mw: float | None
    demand_mw: float
    generation_load_residual_mw: float | None
    compared_lines: int
    flow_magnitude_mae_mw: float | None
    flow_signed_mae_mw: float | None
    flow_reversed_mae_mw: float | None
    model_over_limit_lines: int


@dataclass(frozen=True, slots=True)
class FixedInjectionLine:
    line_id: str
    magnitude_mae_mw: float | None
    signed_mae_mw: float | None
    reversed_mae_mw: float | None
    observed_points: int
    modeled_limit_exceed_count: int


@dataclass(frozen=True, slots=True)
class FixedInjectionReport:
    case_date: str
    buses: int
    lines: int
    generators: int
    modeled_hours: int
    missing_injection_hours: int
    unbalanced_injection_hours: int
    observed_line_points: int
    expected_line_points: int
    flow_magnitude_mae_mw: float | None
    flow_magnitude_rmse_mw: float | None
    flow_signed_mae_mw: float | None
    flow_reversed_mae_mw: float | None
    modeled_line_over_limit_count: int
    hours: tuple[FixedInjectionHour, ...]
    per_line: tuple[FixedInjectionLine, ...]
    disclaimer: str = (
        "Historical PMSS injections held fixed; lossless DC load-flow "
        "diagnostic ONLY. Not PMSS rerun, not bid-price calibration, "
        "not a candidate-bid profit prediction."
    )


def _read(
    history: Mapping[str, Any],
    name: str,
    ids: set[str],
) -> dict[str, Mapping[str, Any]]:
    records = history.get(name)
    if not isinstance(records, list) or len(records) != len(ids):
        raise ValueError(f"Expected complete 24-hour PMSS {name} ID set")
    result: dict[str, Mapping[str, Any]] = {}
    for item in records:
        if not isinstance(item, Mapping):
            raise ValueError(f"Invalid PMSS {name} row")
        if (item.get("market_type") or item.get("marketTypeAtom")) != "DA":
            raise ValueError(f"Wrong market type for PMSS {name}")
        ident = item.get("unit_id") or item.get("element_id") or item.get("elementId")
        if ident is None or str(ident) in result:
            raise ValueError(f"Duplicate/missing PMSS {name} ID")
        result[str(ident)] = item
    if set(result) != ids:
        raise ValueError(f"PMSS {name} IDs disagree with the mapped grid")
    return result


def _mae(errors: list[float]) -> float | None:
    return sum(abs(x) for x in errors) / len(errors) if errors else None


def _rmse(errors: list[float]) -> float | None:
    return sqrt(sum(x*x for x in errors) / len(errors)) if errors else None


def replay_observed_injections(
    network: DcNetwork,
    results: Mapping[str, Any],
    *,
    case_date: str,
    balance_tolerance_mw: float = 0.1,
) -> FixedInjectionReport:
    """DC load-flow from observed PMSS unit MW, not re-optimized offer MW.

    Uses every bus load and every generator's observed dispatched MW, with
    the provided line x and baseMva. All hours with missing unit MW or
    system imbalance above tolerance are flagged and skipped. Missing
    observed branch MW remains missing, never silently replaced by zero.
    """
    try:
        date.fromisoformat(case_date)
    except (ValueError, TypeError) as exc:
        raise ValueError("case_date must be a valid ISO calendar date") from exc
    if not isinstance(results, Mapping) or (
        results.get("marketTypeAtom") != "DA" or results.get("periodNum") != 24
    ):
        raise ValueError("Expected already-observed 24-hour PMSS DA results")
    if (
        isinstance(balance_tolerance_mw, bool)
        or not isfinite(balance_tolerance_mw)
        or balance_tolerance_mw < 0
    ):
        raise ValueError("balance_tolerance_mw must be finite and nonnegative")
    units = _read(results, "unitResults", set(network.unit_bus))
    line_ids = {x.line_id for x in network.lines}
    if not line_ids:
        raise ValueError("Need at least one branch for network flow comparison")
    branches = _read(results, "branchFlows", line_ids)
    power = {uid: series24(row, "accepted_mw", "power") for uid, row in units.items()}
    flow = {uid: series24(row, "flow_mw", "powerFlow") for uid, row in branches.items()}
    if any(
        point is not None and point < 0
        for series in power.values() for point in series
    ):
        raise ValueError("Negative historical generator MW is unsupported")

    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Fixed-injection load-flow requires NumPy") from exc

    bus_index = {bus: index for index, bus in enumerate(network.buses)}
    n = len(bus_index)
    matrix = np.zeros((n, n), dtype=float)
    for branch in network.lines:
        i, j = bus_index[branch.from_bus], bus_index[branch.to_bus]
        weight = network.base_mva / branch.reactance_pu
        matrix[i, i] += weight
        matrix[j, j] += weight
        matrix[i, j] -= weight
        matrix[j, i] -= weight
    slack = bus_index[network.slack_bus]
    remaining = [i for i in range(n) if i != slack]
    reduced = matrix[np.ix_(remaining, remaining)]
    hours: list[FixedInjectionHour] = []
    magnitudes: dict[str, list[float]] = {line.line_id: [] for line in network.lines}
    signed: dict[str, list[float]] = {line.line_id: [] for line in network.lines}
    reversed_sign: dict[str, list[float]] = {line.line_id: [] for line in network.lines}
    over: dict[str, int] = {line.line_id: 0 for line in network.lines}
    missing_hours = imbalance_hours = solved_hours = 0
    for t in range(24):
        demand = sum(series[t] for series in network.hourly_demand_mw.values())
        if any(values[t] is None for values in power.values()):
            missing_hours += 1
            hours.append(FixedInjectionHour(
                t + 1, "MISSING_GENERATION", None, demand, None,
                0, None, None, None, 0,
            ))
            continue
        generation = sum(float(values[t]) for values in power.values())
        residual = generation - demand
        if abs(residual) > balance_tolerance_mw:
            imbalance_hours += 1
            hours.append(FixedInjectionHour(
                t + 1, "GENERATION_LOAD_IMBALANCE", generation, demand, residual,
                0, None, None, None, 0,
            ))
            continue
        injection = np.array(
            [-network.hourly_demand_mw[bus][t] for bus in network.buses], dtype=float
        )
        for unit, series in power.items():
            injection[bus_index[network.unit_bus[unit]]] += float(series[t])
        angles = np.zeros(n, dtype=float)
        if remaining:
            try:
                angles[remaining] = np.linalg.solve(reduced, injection[remaining])
            except np.linalg.LinAlgError as exc:
                raise ValueError("DC topology impedance matrix is singular") from exc

        flow_mag = []
        flow_sign = []
        flow_reverse = []
        over_count = 0
        for line in network.lines:
            prediction = (
                network.base_mva / line.reactance_pu
                * (angles[bus_index[line.from_bus]] - angles[bus_index[line.to_bus]])
            )
            if abs(prediction) > line.limit_mw + 1e-6:
                over[line.line_id] += 1
                over_count += 1
            observed = flow[line.line_id][t]
            if observed is None:
                continue
            magnitude_error = abs(prediction) - abs(observed)
            signed_error = prediction - observed
            reversed_error = -prediction - observed
            magnitudes[line.line_id].append(magnitude_error)
            signed[line.line_id].append(signed_error)
            reversed_sign[line.line_id].append(reversed_error)
            flow_mag.append(magnitude_error)
            flow_sign.append(signed_error)
            flow_reverse.append(reversed_error)
        solved_hours += 1
        hours.append(FixedInjectionHour(
            t + 1, "MODELED", generation, demand, residual,
            len(flow_mag), _mae(flow_mag), _mae(flow_sign),
            _mae(flow_reverse), over_count,
        ))

    all_magnitudes = [x for values in magnitudes.values() for x in values]
    all_signed = [x for values in signed.values() for x in values]
    all_reversed = [x for values in reversed_sign.values() for x in values]
    return FixedInjectionReport(
        case_date=case_date,
        buses=n, lines=len(network.lines), generators=len(network.unit_bus),
        modeled_hours=solved_hours,
        missing_injection_hours=missing_hours,
        unbalanced_injection_hours=imbalance_hours,
        observed_line_points=len(all_magnitudes),
        expected_line_points=24 * len(network.lines),
        flow_magnitude_mae_mw=_mae(all_magnitudes),
        flow_magnitude_rmse_mw=_rmse(all_magnitudes),
        flow_signed_mae_mw=_mae(all_signed),
        flow_reversed_mae_mw=_mae(all_reversed),
        modeled_line_over_limit_count=sum(over.values()),
        hours=tuple(hours),
        per_line=tuple(sorted(
            (
                FixedInjectionLine(
                    line_id=line.line_id,
                    magnitude_mae_mw=_mae(magnitudes[line.line_id]),
                    signed_mae_mw=_mae(signed[line.line_id]),
                    reversed_mae_mw=_mae(reversed_sign[line.line_id]),
                    observed_points=len(magnitudes[line.line_id]),
                    modeled_limit_exceed_count=over[line.line_id],
                )
                for line in network.lines
            ),
            key=lambda row: (
                row.magnitude_mae_mw is None,
                -(row.magnitude_mae_mw or 0),
                row.line_id,
            ),
        )),
    )
