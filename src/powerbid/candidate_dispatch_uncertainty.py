"""EX-ANTE DC dispatch ambiguity screen for a NEW current-rule-legal offer.

Unlike historical tie-break experiments, this screen does not read PMSS
historical clearing results. It holds the original peer bids, 24h nodal
demand and lossless DC network fixed. For each hour it independently
projects the target generator's accepted-MW range on the bid-cost optimal
face. It does NOT imply a unique counterfactual PMSS dispatch or profit.

The interval is a sensitivity range across equally low-COST offline DC
allocations, not a probabilistic prediction interval. Physical 24h UC,
reserve, AC losses, actual PMSS settlement, and unknown tie-breaks remain
outside this research screen.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from powerbid.network_dispatch import DcNetwork, DcOffer
from powerbid.network_strategy import verify_network_inputs
from powerbid.optimal_dispatch_ranges import optimal_unit_dispatch_ranges
from powerbid.pmss_bid_rule_safety import (
    audit_saved_bid_price_limits,
    validate_new_curve,
)
from powerbid.pmss_integration import BidSegment, PMSSSnapshot, PeriodBid, curve_for_period


@dataclass(frozen=True, slots=True)
class CandidateDispatchHour:
    period: int
    minimum_accepted_mw: float
    maximum_accepted_mw: float
    default_lp_accepted_mw: float
    range_width_mw: float
    primary_optimum_offer_cost: float


@dataclass(frozen=True, slots=True)
class CandidateDispatchUncertainty:
    target_unit_id: str
    hours: tuple[CandidateDispatchHour, ...]
    minimum_accepted_mwh: float
    maximum_accepted_mwh: float
    default_lp_accepted_mwh: float
    ambiguous_hours: int
    maximum_hourly_width_mw: float
    original_peer_units_over_current_price_rule: int
    confidence_status: str = "RESEARCH_ONLY_NONUNIQUE_DC_DISPATCH_NO_PMSS_COUNTERFACTUAL"
    safe_for_live_submission: bool = False
    counterfactual_pmss_verified: bool = False
    uses_historical_outcomes_as_forecast: bool = False
    remark: str = (
        "Hourly DC optimal-face target-MW envelope with fixed original peer bids; "
        "NOT a PMSS forecast interval or a simultaneous 24h UC-feasible range. "
        "LMP shown only from the original primary LP, with no 1001 price cap."
    )


def assess_candidate_dispatch_uncertainty(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    target_unit_id: str,
    new_segments: Sequence[BidSegment],
    *,
    ambiguity_threshold_mw: float = 1.0,
    cost_tolerance_abs: float = 1e-6,
    cost_tolerance_rel: float = 1e-11,
) -> CandidateDispatchUncertainty:
    """Calculate offline 24h target generator min/max within optimal offer cost.

    Assumes the SAME legally bounded new offer curve is used all 24 hours.
    Never reads observed PMSS dispatch or nodal prices, even if included
    elsewhere in the uploaded historical snapshot.
    """
    verify_network_inputs(snapshot, network, target_unit_id)
    if snapshot.limits.market_type != "DA" or snapshot.period_num != 24:
        raise ValueError("Only 24-hour PMSS DA research is supported")
    if not isinstance(ambiguity_threshold_mw, (float, int)) or (
        isinstance(ambiguity_threshold_mw, bool)
        or not isfinite(ambiguity_threshold_mw)
        or ambiguity_threshold_mw < 0
    ):
        raise ValueError("Ambiguity threshold must be finite and nonnegative")
    validated = tuple(new_segments)
    validate_new_curve(snapshot, target_unit_id, validated)
    plan = (PeriodBid(1, 24, validated),)
    history_rule = audit_saved_bid_price_limits(snapshot)
    hours = []
    for period in range(1, 25):
        offers: list[DcOffer] = []
        for generator in snapshot.units:
            bands = curve_for_period(
                plan if generator.unit_id == target_unit_id
                else snapshot.bids[generator.unit_id],
                period,
            )
            if not 1 <= len(bands) <= snapshot.limits.max_segments:
                raise ValueError("Original peer curve has unsupported segment count")
            last = 0.0
            for index, band in enumerate(bands, 1):
                if any(not isfinite(value) for value in (
                    band.start_power, band.end_power, band.price
                )) or (
                    abs(band.start_power-last) > 1e-6
                    or band.end_power <= band.start_power or band.price < 0
                ):
                    raise ValueError("Original peer offer is not a valid DC bid curve")
                last = band.end_power
                offers.append(DcOffer(
                    generator.unit_id, index, band.quantity_mw, band.price
                ))
            if last > generator.capacity_mw+1e-6:
                raise ValueError("Original peer offer exceeds mapped generator capacity")
        interval = optimal_unit_dispatch_ranges(
            network,
            offers,
            period,
            cost_tolerance_abs=cost_tolerance_abs,
            cost_tolerance_rel=cost_tolerance_rel,
        )
        target = next(
            item for item in interval.unit_ranges if item.unit_id == target_unit_id
        )
        # No historical PMSS outcome values enter this calculation.
        # The reference price is an unadjusted primary LP model dual only;
        # the interval solver itself does NOT assert new-settlement prices.
        hours.append(CandidateDispatchHour(
            period=period,
            minimum_accepted_mw=target.minimum_mw,
            maximum_accepted_mw=target.maximum_mw,
            default_lp_accepted_mw=target.baseline_mw,
            range_width_mw=target.width_mw,
            primary_optimum_offer_cost=interval.minimum_offer_cost,
        ))
    final_hours = tuple(hours)
    return CandidateDispatchUncertainty(
        target_unit_id=target_unit_id,
        hours=final_hours,
        minimum_accepted_mwh=sum(row.minimum_accepted_mw for row in final_hours),
        maximum_accepted_mwh=sum(row.maximum_accepted_mw for row in final_hours),
        default_lp_accepted_mwh=sum(row.default_lp_accepted_mw for row in final_hours),
        ambiguous_hours=sum(
            row.range_width_mw > ambiguity_threshold_mw for row in final_hours
        ),
        maximum_hourly_width_mw=max(row.range_width_mw for row in final_hours),
        original_peer_units_over_current_price_rule=history_rule.original_units_outside_current_range,
    )
