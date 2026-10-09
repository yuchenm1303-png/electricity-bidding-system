"""Read-only optimal-allocation ambiguity audit for original PMSS bids.

A high point-estimate MAE need not imply the PMSS original dispatch is
suboptimal under the simplified DC offer objective: the minimizer might be
non-unique. Check the *same-hour, jointly fixed* observed generator vector
in the exact DC constraints and compute its minimum offered bid cost.

This uses observed results ONLY for historical diagnosis, never for future
bidding predictions. It makes no claim about real PMSS settlement pricing.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any

from powerbid.network_dispatch import DcOffer, network_from_dict
from powerbid.network_strategy import verify_network_inputs
from powerbid.optimal_dispatch_ranges import optimal_unit_dispatch_ranges
from powerbid.pmss_diagnostics import series24
from powerbid.pmss_integration import curve_for_period, snapshot_from_pmss


@dataclass(frozen=True, slots=True)
class AmbiguityHour:
    period: int
    model_unique_allocation: bool
    max_individual_range_width_mw: float
    mean_individual_range_width_mw: float
    observed_unit_mw_count: int
    observed_within_individual_ranges: int
    observed_jointly_feasible: bool | None
    observed_on_model_optimal_face: bool | None
    observed_bid_cost_gap: float | None


@dataclass(frozen=True, slots=True)
class HistoricalAmbiguityAudit:
    case_date: str
    examined_hours: int
    distinct_units: int
    unique_hours: int
    multiple_optima_hours: int
    observed_complete_hours: int
    observed_joint_network_feasible_hours: int
    observed_joint_model_optimal_hours: int
    observed_individual_in_range: int
    observed_individual_evaluated: int
    mean_individual_range_width_mw: float
    maximum_individual_range_width_mw: float
    maximum_observed_bid_cost_gap: float | None
    hours: tuple[AmbiguityHour, ...]
    disclaimer: str = (
        "Historical original PMSS bids, fixed network and simplified offer cost. "
        "Projected unit intervals are not a jointly feasible box. "
        "Even a 24/24 optimal-cost fit is NOT proof of PMSS rule equivalence, "
        "market-price accuracy, or validation of any NEW bidding strategy."
    )


def audit_historical_optimal_ambiguity(
    raw: Mapping[str, Any],
) -> HistoricalAmbiguityAudit:
    if not isinstance(raw, Mapping) or raw.get("historicalBacktestOnly") is not True:
        raise ValueError("Only explicitly tagged historical PMSS snapshots may be analyzed")
    label = str(raw.get("caseDate") or "")
    try:
        valid_day = date.fromisoformat(label)
    except ValueError as exc:
        raise ValueError("Historical caseDate must be YYYY-MM-DD") from exc
    if valid_day.isoformat() != label:
        raise ValueError("Historical caseDate must be YYYY-MM-DD")
    actual = raw.get("results")
    if not isinstance(actual, Mapping) or (
        actual.get("marketTypeAtom") != "DA" or actual.get("periodNum") != 24
    ):
        raise ValueError("Requires 24-hour already-observed PMSS DA results")
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    network = network_from_dict(raw["dcNetwork"])
    verify_network_inputs(snapshot, network, snapshot.units[0].unit_id)
    units = {item.unit_id for item in snapshot.units}
    results = actual.get("unitResults")
    if not isinstance(results, list) or len(results) != len(units):
        raise ValueError("Historical unit results must cover all mapped generators")
    observed: dict[str, tuple[float | None, ...]] = {}
    for item in results:
        if not isinstance(item, Mapping) or (
            item.get("market_type") or item.get("marketTypeAtom")
        ) != "DA":
            raise ValueError("Incorrect historical unit result or market type")
        identifier = str(
            item.get("unit_id") or item.get("element_id") or item.get("elementId") or ""
        )
        if not identifier or identifier in observed:
            raise ValueError("Missing or duplicate observed generator ID")
        observed[identifier] = series24(item, "accepted_mw", "power")
    if set(observed) != units:
        raise ValueError("Historical generator IDs disagree with verified network")
    if any(value is not None and (not isfinite(value) or value < 0)
           for series in observed.values() for value in series):
        raise ValueError("Observed generator dispatch must be finite nonnegative")

    summaries: list[AmbiguityHour] = []
    widths: list[float] = []
    optimal = feasible = complete = unique = within = tested = 0
    gaps: list[float] = []
    for hour in range(1, 25):
        offers: list[DcOffer] = []
        for unit in snapshot.units:
            blocks = curve_for_period(snapshot.bids[unit.unit_id], hour)
            if not 1 <= len(blocks) <= snapshot.limits.max_segments:
                raise ValueError("Invalid original PMSS offer segment count")
            last = 0.0
            for number, block in enumerate(blocks, 1):
                if any(not isfinite(v) for v in
                       (block.start_power, block.end_power, block.price)):
                    raise ValueError("Original bid contains a nonfinite value")
                if (abs(block.start_power-last) > 1e-6 or
                        block.end_power <= block.start_power or block.price < 0):
                    raise ValueError("Original PMSS offer curve is invalid")
                last = block.end_power
                offers.append(
                    DcOffer(unit.unit_id, number, block.quantity_mw, block.price)
                )
            if last > unit.capacity_mw+1e-6:
                raise ValueError("Original PMSS bid exceeds unit power capacity")
        observed_vector = {
            unit: observed[unit][hour-1] for unit in units
        }
        complete_hour = all(val is not None for val in observed_vector.values())
        observed_all = (
            {unit: float(val) for unit, val in observed_vector.items() if val is not None}
            if complete_hour else None
        )
        response = optimal_unit_dispatch_ranges(
            network, offers, hour, observed_unit_mw=observed_all
        )
        unique += int(response.unique_dispatch_within_tolerance)
        observed_within = 0
        for unit_range in response.unit_ranges:
            widths.append(unit_range.width_mw)
            value = observed_vector[unit_range.unit_id]
            if value is None:
                continue
            tested += 1
            if (unit_range.minimum_mw-1e-3 <= value
                    <= unit_range.maximum_mw+1e-3):
                within += 1
                observed_within += 1
        if complete_hour:
            complete += 1
        if response.observed_jointly_network_feasible:
            feasible += 1
        if response.observed_on_optimal_cost_face:
            optimal += 1
        if response.observed_bid_cost_gap is not None:
            gaps.append(response.observed_bid_cost_gap)
        hour_widths = [v.width_mw for v in response.unit_ranges]
        summaries.append(
            AmbiguityHour(
                period=hour,
                model_unique_allocation=response.unique_dispatch_within_tolerance,
                max_individual_range_width_mw=max(hour_widths),
                mean_individual_range_width_mw=sum(hour_widths)/len(hour_widths),
                observed_unit_mw_count=sum(
                    val is not None for val in observed_vector.values()
                ),
                observed_within_individual_ranges=observed_within,
                observed_jointly_feasible=response.observed_jointly_network_feasible,
                observed_on_model_optimal_face=response.observed_on_optimal_cost_face,
                observed_bid_cost_gap=response.observed_bid_cost_gap,
            )
        )
    return HistoricalAmbiguityAudit(
        case_date=label, examined_hours=24, distinct_units=len(units),
        unique_hours=unique, multiple_optima_hours=24-unique,
        observed_complete_hours=complete,
        observed_joint_network_feasible_hours=feasible,
        observed_joint_model_optimal_hours=optimal,
        observed_individual_in_range=within, observed_individual_evaluated=tested,
        mean_individual_range_width_mw=sum(widths)/len(widths),
        maximum_individual_range_width_mw=max(widths),
        maximum_observed_bid_cost_gap=max(gaps) if gaps else None,
        hours=tuple(summaries),
    )
