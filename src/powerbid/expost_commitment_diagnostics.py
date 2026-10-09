"""Ex-post historical zero-output sensitivity in the OFFLINE bid-based DC model.

We run two counterfactuals of ORIGINAL PMSS bids:
 A) ordinary independent single-hour DC bid clearing;
 B) identical DC clearing, additionally disabling units that PMSS *actually*
    dispatched at zero MW in that particular historical hour.

This is a diagnostic with look-ahead. Observed zero MW does NOT establish
real unit on/off status (notably when Pmin=0). B must NOT be used for future
recommendations or claimed to reproduce PMSS commitment / pricing rules.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any

from powerbid.network_dispatch import (
    DcInfeasibleError,
    DcOffer,
    dc_clear_hour,
    network_from_dict,
)
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_diagnostics import series24
from powerbid.pmss_integration import curve_for_period, snapshot_from_pmss


@dataclass(frozen=True, slots=True)
class ExpostHour:
    period: int
    observed_zero_mw_units: int
    model_dispatched_observed_zero_units: int
    baseline_dispatch_mae_mw: float | None
    masked_dispatch_mae_mw: float | None
    baseline_line_abs_mae_mw: float | None
    masked_line_abs_mae_mw: float | None
    baseline_nodal_price_mae: float | None
    masked_nodal_price_mae: float | None
    status: str


@dataclass(frozen=True, slots=True)
class ExpostUnit:
    unit_id: str
    observed_zero_hours: int
    baseline_dispatched_when_observed_zero_hours: int
    baseline_mae_mw: float | None
    masked_mae_mw: float | None
    compared_hours: int


@dataclass(frozen=True, slots=True)
class ExpostAvailabilityReport:
    case_date: str
    all_hours: int
    paired_hours: int
    missing_observation_hours: int
    masked_infeasible_hours: int
    observed_zero_unit_hours: int
    baseline_positive_on_observed_zero_unit_hours: int
    baseline_paired_dispatch_mae_mw: float | None
    masked_paired_dispatch_mae_mw: float | None
    baseline_paired_line_abs_mae_mw: float | None
    masked_paired_line_abs_mae_mw: float | None
    baseline_paired_nodal_price_mae: float | None
    masked_paired_nodal_price_mae: float | None
    hours: tuple[ExpostHour, ...]
    units: tuple[ExpostUnit, ...]
    disclaimer: str = (
        "EX-POST zero-MW restriction using SAME-DAY observed PMSS data. "
        "Zero output does not prove offline status; no causal attribution, "
        "no genuine PMSS commitment reconstruction, no candidate-bid "
        "profit forecast and no PMSS write/execute."
    )


def _read_rows(actual: Mapping[str, Any], key: str, ids: set[str]):
    rows = actual.get(key)
    if not isinstance(rows, list) or len(rows) != len(ids):
        raise ValueError(f"Historical {key} must have every expected ID")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError(f"Historical {key} row is not an object")
        if (row.get("market_type") or row.get("marketTypeAtom")) != "DA":
            raise ValueError(f"Historical {key} market type must be DA")
        ident = row.get("unit_id") or row.get("element_id") or row.get("elementId")
        if ident is None or str(ident) in result:
            raise ValueError(f"Duplicate or missing historical {key} ID")
        result[str(ident)] = row
    if set(result) != ids:
        raise ValueError(f"Historical {key} IDs do not match the verified network")
    return result


def _mae(errors: list[float]) -> float | None:
    return sum(abs(x) for x in errors) / len(errors) if errors else None


def replay_zero_output_restriction(
    raw: Mapping[str, Any],
    *,
    zero_tolerance_mw: float = 1e-6,
) -> ExpostAvailabilityReport:
    """Compare equal observed points per hour; never impute missing PMSS MW.

    The 'forced off' hypothesis uses FUTURE/HISTORICAL outcomes and therefore
    is only an ex-post explanation of disagreement, never forward strategy.
    """
    if not isinstance(raw, Mapping) or raw.get("historicalBacktestOnly") is not True:
        raise ValueError("Requires explicitly labelled historical-only snapshot")
    case_date = str(raw.get("caseDate") or "")
    try:
        parsed = date.fromisoformat(case_date)
    except (ValueError, TypeError) as exc:
        raise ValueError("Require an ISO historical caseDate") from exc
    if parsed.isoformat() != case_date:
        raise ValueError("Require YYYY-MM-DD historical caseDate")
    if not isfinite(zero_tolerance_mw) or not 0 <= zero_tolerance_mw <= 1:
        raise ValueError("zero_tolerance_mw must be between 0 and 1")
    actual = raw.get("results")
    if not isinstance(actual, Mapping) or (
        actual.get("marketTypeAtom") != "DA" or actual.get("periodNum") != 24
    ):
        raise ValueError("Requires exact 24-hour observed PMSS DA results")

    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"],
        unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    network = network_from_dict(raw["dcNetwork"])
    verify_network_inputs(snapshot, network, snapshot.units[0].unit_id)
    unit_ids = set(network.unit_bus)
    unit_rows = _read_rows(actual, "unitResults", unit_ids)
    line_rows = _read_rows(actual, "branchFlows", {x.line_id for x in network.lines})
    node_rows = _read_rows(actual, "nodalPrices", set(network.buses))
    power = {key: series24(row, "accepted_mw", "power") for key, row in unit_rows.items()}
    flows = {key: series24(row, "flow_mw", "powerFlow") for key, row in line_rows.items()}
    prices = {key: series24(row, "lmp", "powerFlow") for key, row in node_rows.items()}
    if any(v is not None and v < 0 for series in power.values() for v in series):
        raise ValueError("Negative observed generation is unsupported")

    observations: list[ExpostHour] = []
    unit_zero_counts = {id_: 0 for id_ in unit_ids}
    unit_mismatch_counts = {id_: 0 for id_ in unit_ids}
    unit_base_errors = {id_: [] for id_ in unit_ids}
    unit_mask_errors = {id_: [] for id_ in unit_ids}
    paired_baseline_dispatch: list[float] = []
    paired_masked_dispatch: list[float] = []
    paired_baseline_line: list[float] = []
    paired_masked_line: list[float] = []
    paired_baseline_price: list[float] = []
    paired_masked_price: list[float] = []
    missing = infeasible = pairs = 0

    for t in range(24):
        if any(values[t] is None for values in power.values()):
            missing += 1
            observations.append(ExpostHour(
                t+1, 0, 0, None, None, None, None, None, None,
                "MISSING_HISTORICAL_DISPATCH",
            ))
            continue
        offers: list[DcOffer] = []
        for unit in snapshot.units:
            blocks = curve_for_period(snapshot.bids[unit.unit_id], t+1)
            last = 0.0
            if not 1 <= len(blocks) <= snapshot.limits.max_segments:
                raise ValueError("Invalid original bid curve length")
            for k, block in enumerate(blocks, 1):
                if (
                    not all(isfinite(value) for value in (
                        block.start_power, block.end_power, block.price
                    ))
                    or abs(block.start_power-last) > 1e-6
                    or block.end_power <= block.start_power
                    or block.price < 0
                ):
                    raise ValueError("Invalid original bid curve")
                last = block.end_power
                offers.append(DcOffer(unit.unit_id, k, block.quantity_mw, block.price))
            if last > unit.capacity_mw+1e-6:
                raise ValueError("Original bid exceeds known unit capacity")
        observed_off = frozenset(
            key for key, values in power.items()
            if values[t] <= zero_tolerance_mw
        )
        for uid in observed_off:
            unit_zero_counts[uid] += 1
        baseline = dc_clear_hour(network, offers, t+1)
        missed = sum(baseline.accepted_by_unit[uid] > zero_tolerance_mw for uid in observed_off)
        for uid in observed_off:
            if baseline.accepted_by_unit[uid] > zero_tolerance_mw:
                unit_mismatch_counts[uid] += 1

        def errors(dispatch, hour_idx=t):
            unit_error = {
                uid: dispatch.accepted_by_unit[uid] - float(power[uid][hour_idx])
                for uid in unit_ids
            }
            line_error = [
                abs(abs(dispatch.line_flows_mw[line]) - abs(observed[hour_idx]))
                for line, observed in flows.items() if observed[hour_idx] is not None
            ]
            price_error = [
                abs(dispatch.nodal_prices[bus] - observed[hour_idx])
                for bus, observed in prices.items() if observed[hour_idx] is not None
            ]
            return unit_error, line_error, price_error

        orig_unit, orig_line, orig_price = errors(baseline)
        try:
            masked = dc_clear_hour(
                network, offers, t+1, forced_off_units=observed_off
            )
        except DcInfeasibleError:
            infeasible += 1
            observations.append(ExpostHour(
                t+1, len(observed_off), missed, _mae(list(orig_unit.values())),
                None, _mae(orig_line), None, _mae(orig_price), None,
                "MASKED_DISPATCH_INFEASIBLE",
            ))
            continue
        pairs += 1
        mask_unit, mask_line, mask_price = errors(masked)
        for uid in unit_ids:
            unit_base_errors[uid].append(orig_unit[uid])
            unit_mask_errors[uid].append(mask_unit[uid])
        paired_baseline_dispatch.extend(orig_unit.values())
        paired_masked_dispatch.extend(mask_unit.values())
        paired_baseline_line.extend(orig_line)
        paired_masked_line.extend(mask_line)
        paired_baseline_price.extend(orig_price)
        paired_masked_price.extend(mask_price)
        observations.append(ExpostHour(
            t+1, len(observed_off), missed,
            _mae(list(orig_unit.values())),
            _mae(list(mask_unit.values())),
            _mae(orig_line), _mae(mask_line),
            _mae(orig_price), _mae(mask_price),
            "PAIRED",
        ))
    return ExpostAvailabilityReport(
        case_date=case_date,
        all_hours=24,
        paired_hours=pairs,
        missing_observation_hours=missing,
        masked_infeasible_hours=infeasible,
        observed_zero_unit_hours=sum(unit_zero_counts.values()),
        baseline_positive_on_observed_zero_unit_hours=sum(unit_mismatch_counts.values()),
        baseline_paired_dispatch_mae_mw=_mae(paired_baseline_dispatch),
        masked_paired_dispatch_mae_mw=_mae(paired_masked_dispatch),
        baseline_paired_line_abs_mae_mw=_mae(paired_baseline_line),
        masked_paired_line_abs_mae_mw=_mae(paired_masked_line),
        baseline_paired_nodal_price_mae=_mae(paired_baseline_price),
        masked_paired_nodal_price_mae=_mae(paired_masked_price),
        hours=tuple(observations),
        units=tuple(
            ExpostUnit(
                unit_id=uid,
                observed_zero_hours=unit_zero_counts[uid],
                baseline_dispatched_when_observed_zero_hours=unit_mismatch_counts[uid],
                baseline_mae_mw=_mae(unit_base_errors[uid]),
                masked_mae_mw=_mae(unit_mask_errors[uid]),
                compared_hours=pairs,
            )
            for uid in sorted(unit_ids)
        ),
    )
