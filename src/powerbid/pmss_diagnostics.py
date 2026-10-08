"""Descriptive diagnostics for observed PMSS node prices and branch flows.

IMPORTANT: these are *ex-post* PMSS network outcomes, not predictions of how
network constraints react to a candidate bid. Never feed them into a local
uniform-price reclear as though they were counterfactual LMPs.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any

from powerbid.pmss_strategy import CurveEvaluation


def series24(row: Mapping[str, Any], *names: str) -> tuple[float | None, ...]:
    """Read either unmodified PMSS {datas:[...]} or normalized lists/tuples."""
    val = next((row[key] for key in names if key in row), None)
    if isinstance(val, Mapping):
        val = val.get("datas")
    if not isinstance(val, (list, tuple)) or len(val) != 24:
        raise ValueError(f"Missing 24-point PMSS series: {names}")
    out = []
    for x in val:
        if x is None:
            out.append(None)
            continue
        if isinstance(x, bool) or isinstance(x, (dict, list, tuple)):
            raise ValueError(f"Unsupported point type for {names}")
        try:
            number = float(x)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Non-numeric PMSS series value: {names}") from exc
        if not isfinite(number):
            raise ValueError(f"Non-finite PMSS series value: {names}")
        out.append(number)
    return tuple(out)


def _identity(row: Mapping[str, Any]) -> str:
    ident = row.get("element_id", row.get("unit_id", row.get("elementId")))
    return str(ident) if ident is not None else ""


def _market_type(row: Mapping[str, Any]) -> str:
    return str(row.get("market_type", row.get("marketTypeAtom", "")))


def _items(results: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    raw = results.get(name)
    if not isinstance(raw, list):
        raise ValueError(f"Missing PMSS {name} results")
    if not raw or any(not isinstance(item, Mapping) for item in raw):
        raise ValueError(f"Empty or invalid PMSS {name} results")
    identifiers = [_identity(row) for row in raw]
    if any(not ident for ident in identifiers) or len(set(identifiers)) != len(raw):
        raise ValueError(f"Duplicate or missing PMSS {name} IDs")
    if any(_market_type(item) != "DA" for item in raw):
        raise ValueError(f"PMSS {name} contains non-DA outcomes")
    return raw


@dataclass(frozen=True, slots=True)
class NetworkHour:
    hour: int
    nodes_with_price: int
    branches_with_flow: int
    mean_lmp: float | None
    min_lmp: float | None
    max_lmp: float | None
    lmp_spread: float | None
    nonzero_shadow_branches: int
    max_abs_shadow: float | None
    max_abs_flow_mw: float | None


@dataclass(frozen=True, slots=True)
class MonitoredBranch:
    element_id: str
    name: str
    hours_nonzero_shadow: int
    peak_abs_shadow: float
    peak_abs_flow_mw: float | None


@dataclass(frozen=True, slots=True)
class HistoricalNetworkReport:
    period_num: int
    node_count: int
    branch_count: int
    hourly: tuple[NetworkHour, ...]
    most_shadowed: tuple[MonitoredBranch, ...]
    price_coverage_points: int
    flow_coverage_points: int
    label: str = "PMSS historical observed network results (not simulated bid response)"


def analyze_historical_network(
    results: Mapping[str, Any],
    *,
    market_type: str = "DA",
    shadow_epsilon: float = 1e-6,
) -> HistoricalNetworkReport:
    if market_type != "DA" or results.get("marketTypeAtom") != "DA":
        raise ValueError("Network reporting currently supports DA results only")
    if int(results.get("periodNum", 0)) != 24:
        raise ValueError("Expected 24-hour PMSS results")
    if not isfinite(shadow_epsilon) or shadow_epsilon < 0:
        raise ValueError("shadow_epsilon must be finite and nonnegative")
    nodes = _items(results, "nodalPrices")
    branches = _items(results, "branchFlows")
    nodal_prices = [series24(item, "lmp", "powerFlow") for item in nodes]
    flows = [series24(item, "flow_mw", "powerFlow") for item in branches]
    shadows = [series24(item, "shadow_price", "shadowPrice") for item in branches]
    hours = []
    for hour in range(24):
        prices = [row[hour] for row in nodal_prices if row[hour] is not None]
        branch_flows = [row[hour] for row in flows if row[hour] is not None]
        branch_shadows = [row[hour] for row in shadows if row[hour] is not None]
        hours.append(NetworkHour(
            hour=hour + 1,
            nodes_with_price=len(prices),
            branches_with_flow=len(branch_flows),
            mean_lmp=sum(prices) / len(prices) if prices else None,
            min_lmp=min(prices) if prices else None,
            max_lmp=max(prices) if prices else None,
            lmp_spread=max(prices) - min(prices) if prices else None,
            nonzero_shadow_branches=sum(
                abs(x) > shadow_epsilon for x in branch_shadows
            ),
            max_abs_shadow=max(map(abs, branch_shadows)) if branch_shadows else None,
            max_abs_flow_mw=max(map(abs, branch_flows)) if branch_flows else None,
        ))
    monitored = []
    for branch, flow, shadow in zip(branches, flows, shadows, strict=True):
        counts = sum(x is not None and abs(x) > shadow_epsilon for x in shadow)
        peak_shadow = max((abs(x) for x in shadow if x is not None), default=0.0)
        peak_flow = max((abs(x) for x in flow if x is not None), default=None)
        monitored.append(MonitoredBranch(
            element_id=_identity(branch),
            name=str(branch.get("name", branch.get("elementName", ""))),
            hours_nonzero_shadow=counts,
            peak_abs_shadow=peak_shadow,
            peak_abs_flow_mw=peak_flow,
        ))
    monitored.sort(
        key=lambda row: (-row.hours_nonzero_shadow, -row.peak_abs_shadow, row.element_id)
    )
    return HistoricalNetworkReport(
        period_num=24,
        node_count=len(nodes),
        branch_count=len(branches),
        hourly=tuple(hours),
        most_shadowed=tuple(monitored),
        price_coverage_points=sum(x.nodes_with_price for x in hours),
        flow_coverage_points=sum(x.branches_with_flow for x in hours),
    )


@dataclass(frozen=True, slots=True)
class BacktestHour:
    hour: int
    observed_accepted_mw: float | None
    surrogate_accepted_mw: float
    absolute_error_mw: float | None
    observed_unit_price: float | None
    surrogate_uniform_price: float | None


@dataclass(frozen=True, slots=True)
class BaselineBacktest:
    target_unit_id: str
    hours: tuple[BacktestHour, ...]
    observed_power_points: int
    power_mae_mw: float | None
    power_rmse_mw: float | None
    observed_price_points: int
    label: str = "Baseline-only historical diagnostic; NOT a candidate-bid PMSS result"


def compare_baseline_to_pmss(
    *,
    target_unit_id: str,
    baseline: CurveEvaluation,
    results: Mapping[str, Any],
) -> BaselineBacktest:
    """Quantify local model mismatch using the original PMSS *submitted* curve.

    Do not treat a candidate curve's simulated dispatch as a prediction of
    PMSS dispatch. Do not treat the uniform system price as nodal settlement.
    """
    if int(results.get("periodNum", 0)) != 24 or results.get("marketTypeAtom") != "DA":
        raise ValueError("PMSS historical result must be 24h DA")
    units = _items(results, "unitResults")
    rows = [r for r in units if _identity(r) == target_unit_id]
    if len(rows) != 1:
        raise ValueError("Target PMSS unit ID was not found uniquely")
    if len(baseline.hours) != 24:
        raise ValueError("Expected 24 baseline hourly simulations")
    actual = series24(rows[0], "accepted_mw", "power")
    unit_price = series24(rows[0], "clearing_prices", "price")
    samples = []
    abs_errors = []
    squared_errors = []
    for idx, hour in enumerate(baseline.hours):
        if hour.period != idx + 1:
            raise ValueError("Baseline periods must be strictly ordered 1..24")
        observed = actual[idx]
        error = abs(hour.target_accepted_mw - observed) if observed is not None else None
        if error is not None:
            abs_errors.append(error)
            squared_errors.append(error * error)
        samples.append(BacktestHour(
            hour=hour.period,
            observed_accepted_mw=observed,
            surrogate_accepted_mw=hour.target_accepted_mw,
            absolute_error_mw=error,
            observed_unit_price=unit_price[idx],
            surrogate_uniform_price=hour.clearing_price,
        ))
    return BaselineBacktest(
        target_unit_id=target_unit_id,
        hours=tuple(samples),
        observed_power_points=len(abs_errors),
        power_mae_mw=sum(abs_errors) / len(abs_errors) if abs_errors else None,
        power_rmse_mw=sqrt(sum(squared_errors) / len(squared_errors))
        if squared_errors else None,
        observed_price_points=sum(p is not None for p in unit_price),
    )
