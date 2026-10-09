"""Read-only historical comparison of two EX-ANTE deterministic DC tie-breaks.

Never choose a winner using the historical dispatch and call it forward
validation. This study quantifies the sensitivity of a single optimal LP
allocation to a stated unit-ID rule; PMSS's actual tie-breaking is unknown.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any

from powerbid.deterministic_dc_tiebreak import select_dc_optimal_tiebreak
from powerbid.network_dispatch import DcOffer, network_from_dict
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_diagnostics import series24
from powerbid.pmss_integration import curve_for_period, snapshot_from_pmss


@dataclass(frozen=True, slots=True)
class TieBreakHour:
    period: int
    complete_observation: bool
    baseline_mae_mw: float | None
    ascending_mae_mw: float | None
    descending_mae_mw: float | None
    ascending_vs_descending_total_mw_shift: float
    max_primary_cost_increase: float


@dataclass(frozen=True, slots=True)
class HistoricalTieBreakStudy:
    case_date: str
    generator_count: int
    examined_hours: int
    compared_hours: int
    baseline_dispatch_mae_mw: float | None
    ascending_dispatch_mae_mw: float | None
    descending_dispatch_mae_mw: float | None
    hours_with_different_deterministic_allocations: int
    maximum_total_allocation_difference_mw: float
    maximum_primary_bid_cost_increase: float
    hours: tuple[TieBreakHour, ...]
    disclaimer: str = (
        "Both priorities are synthetic ex-ante ID conventions, not PMSS rules. "
        "Historical comparison is purely EX-POST; never select a fitted priority "
        "for future bidding based only on this or claim candidate-bid validation."
    )


def audit_historical_tiebreaks(raw: Mapping[str, Any]) -> HistoricalTieBreakStudy:
    if not isinstance(raw, Mapping) or raw.get("historicalBacktestOnly") is not True:
        raise ValueError("Only explicitly historical PMSS snapshots are accepted")
    case_date = str(raw.get("caseDate") or "")
    try:
        parsed = date.fromisoformat(case_date)
    except ValueError as exc:
        raise ValueError("Historical caseDate must be ISO YYYY-MM-DD") from exc
    if parsed.isoformat() != case_date:
        raise ValueError("Historical caseDate must be ISO YYYY-MM-DD")
    data = raw.get("results")
    if not isinstance(data, Mapping) or (
        data.get("marketTypeAtom") != "DA" or data.get("periodNum") != 24
    ):
        raise ValueError("Require original PMSS 24h DA history")
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"], demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    network = network_from_dict(raw["dcNetwork"])
    verify_network_inputs(snapshot, network, snapshot.units[0].unit_id)
    identifiers = tuple(sorted(network.unit_bus))
    unit_rows = data.get("unitResults")
    if not isinstance(unit_rows, list) or len(unit_rows) != len(identifiers):
        raise ValueError("Unit observations do not cover every generator")
    observations = {}
    for row in unit_rows:
        if not isinstance(row, Mapping) or (
            row.get("market_type") or row.get("marketTypeAtom")
        ) != "DA":
            raise ValueError("Historical generator row is not DA")
        key = row.get("unit_id") or row.get("element_id") or row.get("elementId")
        if key is None or str(key) in observations:
            raise ValueError("Missing or duplicate historical generator ID")
        observations[str(key)] = series24(row, "accepted_mw", "power")
    if set(observations) != set(identifiers):
        raise ValueError("Historical generator IDs do not match topology")
    if any(
        value is not None and (not isfinite(value) or value < 0)
        for series in observations.values() for value in series
    ):
        raise ValueError("Observed generation must be finite nonnegative")

    raw_error: list[float] = []
    asc_error: list[float] = []
    desc_error: list[float] = []
    reported: list[TieBreakHour] = []
    differing_hours = 0
    highest_shift = largest_cost_increase = 0.0
    for hour in range(1, 25):
        supply = []
        for generator in snapshot.units:
            blocks = curve_for_period(snapshot.bids[generator.unit_id], hour)
            if not 1 <= len(blocks) <= snapshot.limits.max_segments:
                raise ValueError("Invalid saved original offer block count")
            start = 0.0
            for i, block in enumerate(blocks, 1):
                if (any(not isfinite(v) for v in (
                    block.start_power, block.end_power, block.price
                )) or abs(block.start_power-start) > 1e-6
                        or block.end_power <= block.start_power or block.price < 0):
                    raise ValueError("Invalid historical original bid")
                start = block.end_power
                supply.append(DcOffer(generator.unit_id, i, block.quantity_mw, block.price))
            if start > generator.capacity_mw + 1e-6:
                raise ValueError("Original bid exceeds unit capacity")
        increasing = select_dc_optimal_tiebreak(
            network, supply, hour, unit_priority=identifiers
        )
        decreasing = select_dc_optimal_tiebreak(
            network, supply, hour, unit_priority=tuple(reversed(identifiers))
        )
        shift = sum(
            abs(increasing.selected_mw[uid]-decreasing.selected_mw[uid])
            for uid in identifiers
        )
        highest_shift = max(highest_shift, shift)
        differing_hours += int(shift > 1e-3)
        cost_change = max(
            abs(increasing.selected_bid_cost-increasing.primary_optimum_bid_cost),
            abs(decreasing.selected_bid_cost-decreasing.primary_optimum_bid_cost),
        )
        largest_cost_increase = max(largest_cost_increase, cost_change)
        complete = all(observations[uid][hour-1] is not None for uid in identifiers)
        baseline_hour = ascending_hour = descending_hour = None
        if complete:
            original_errors = [
                abs(increasing.original_lp_selected_mw[uid]-observations[uid][hour-1])
                for uid in identifiers
            ]
            positive_errors = [
                abs(increasing.selected_mw[uid]-observations[uid][hour-1])
                for uid in identifiers
            ]
            negative_errors = [
                abs(decreasing.selected_mw[uid]-observations[uid][hour-1])
                for uid in identifiers
            ]
            raw_error.extend(original_errors)
            asc_error.extend(positive_errors)
            desc_error.extend(negative_errors)
            baseline_hour = sum(original_errors)/len(identifiers)
            ascending_hour = sum(positive_errors)/len(identifiers)
            descending_hour = sum(negative_errors)/len(identifiers)
        reported.append(
            TieBreakHour(
                period=hour,
                complete_observation=complete,
                baseline_mae_mw=baseline_hour,
                ascending_mae_mw=ascending_hour,
                descending_mae_mw=descending_hour,
                ascending_vs_descending_total_mw_shift=shift,
                max_primary_cost_increase=cost_change,
            )
        )

    def mean(error: list[float]) -> float | None:
        return sum(error)/len(error) if error else None

    return HistoricalTieBreakStudy(
        case_date=case_date,
        generator_count=len(identifiers),
        examined_hours=24,
        compared_hours=sum(int(item.complete_observation) for item in reported),
        baseline_dispatch_mae_mw=mean(raw_error),
        ascending_dispatch_mae_mw=mean(asc_error),
        descending_dispatch_mae_mw=mean(desc_error),
        hours_with_different_deterministic_allocations=differing_hours,
        maximum_total_allocation_difference_mw=highest_shift,
        maximum_primary_bid_cost_increase=largest_cost_increase,
        hours=tuple(reported),
    )
