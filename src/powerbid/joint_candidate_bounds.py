"""Read-only 24-hour DC+UC economic-optimum target-MWh envelope.

This differs fundamentally from the existing independent-hour DC dispatch
ranges: BOTH extremal schedules satisfy the SAME integrated 24-hour network,
unit commitment, min-up/down, ramp and startup/shutdown constraints.

No machine data are guessed. This module only accepts complete explicitly
provenanced technical records; 'course_verified_by_user' is a user assertion,
not independent verification of PMSS semantics. 'synthetic' is teaching-only.
There are NO PMSS network requests and NO settlement-price projections.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

from powerbid.joint_market import JointMwhExtreme, joint_clear_day
from powerbid.network_dispatch import DcNetwork
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_bid_rule_safety import validate_new_curve
from powerbid.pmss_integration import BidSegment, PeriodBid, PMSSSnapshot
from powerbid.pmss_joint_research import (
    JointReadiness,
    _spec,
    assess_joint_readiness,
)


@dataclass(frozen=True, slots=True)
class JointCandidateMwhEnvelope:
    target_unit_id: str
    minimum_accepted_mwh: float
    maximum_accepted_mwh: float
    minimum_24h_dispatch_mw: tuple[float, ...]
    maximum_24h_dispatch_mw: tuple[float, ...]
    minimum_24h_online: tuple[bool, ...]
    maximum_24h_online: tuple[bool, ...]
    minimum_primary_cost: float
    maximum_primary_cost: float
    minimum_schedule_cost: float
    maximum_schedule_cost: float
    allowed_primary_cost_increase: float
    terminal_mode: str
    technical_source: str
    technical_source_description: str
    readiness: JointReadiness
    model_status: str = "COMPLETE_INPUTS_24H_COUPLED_DC_UC_RESEARCH"
    safe_for_live_submission: bool = False
    independent_pmss_technical_verification: bool = False
    counterfactual_pmss_verified: bool = False
    uses_historical_outcomes_as_forecast: bool = False
    disclaimer: str = (
        "Both extrema are separate near-optimal 24h integrated MILP "
        "schedules, with potentially different generator commitments; "
        "the interval does NOT describe PMSS's actual market tie-break, "
        "nodal settlement, probabilistic uncertainty or verified profit."
    )


def assess_joint_candidate_mwh_envelope(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    technical: Mapping[str, Any],
    target_unit_id: str,
    new_segments: Sequence[BidSegment],
    *,
    technical_source: str,
    technical_source_description: str,
    terminal_mode: str = "carryover",
    solver_time_limit_seconds: float = 12.0,
) -> JointCandidateMwhEnvelope:
    """Find daily minimum and maximum target energy on a joint economic face.

    Both optimizations use the same unchanged candidate and peer offers;
    first solve the primary economic 24h MILP, then constrain its full
    objective (including startup/shutdown cost) to the optimum+small tolerance
    before separately minimizing or maximizing target daily MWh.
    """
    verify_network_inputs(snapshot, network, target_unit_id)
    if type(technical_source) is not str or technical_source not in (
        "synthetic", "course_verified_by_user",
    ):
        raise ValueError(
            "Real technical data must be explicitly course_verified_by_user; "
            "synthetic runs are teaching-only, unverified input is rejected"
        )
    if (type(technical_source_description) is not str
            or not technical_source_description.strip()
            or len(technical_source_description) > 500):
        raise ValueError("A specific and concise technical parameter source is required")
    if terminal_mode not in ("complete", "carryover"):
        raise ValueError("Unsupported integrated terminal mode")
    if type(solver_time_limit_seconds) not in (int, float) or (
        not isfinite(solver_time_limit_seconds)
        or not 1 <= solver_time_limit_seconds <= 30
    ):
        raise ValueError("Joint solver limit must be 1..30 seconds per MILP")
    if len(network.buses) > 60 or len(network.lines) > 90 or len(snapshot.units) > 12:
        raise ValueError("Integrated range research exceeds limited network/units budget")

    segments = tuple(new_segments)
    validate_new_curve(snapshot, target_unit_id, segments)
    readiness = assess_joint_readiness(snapshot, technical, source=technical_source)
    if not readiness.ready:
        raise ValueError(
            "Joint 24h physical range BLOCKED: missing/invalid machine parameters "
            "or unverifiable source, "
            f"missing={readiness.missing_unit_ids}, "
            f"unknown={readiness.unexpected_unit_ids}, "
            f"invalid={readiness.invalid}"
        )
    specs = {uid: _spec(uid, values) for uid, values in technical.items()}
    plan = (PeriodBid(1, 24, segments),)
    extrema: list[JointMwhExtreme] = []
    for direction in ("minimum", "maximum"):
        value = joint_clear_day(
            snapshot, network, specs, target_unit_id,
            candidate_plan=plan, terminal_mode=terminal_mode,
            time_limit_seconds=solver_time_limit_seconds,
            target_mwh_extreme=direction,
        )
        if not isinstance(value, JointMwhExtreme):
            raise RuntimeError("24h physical envelope expected a solver projection")
        extrema.append(value)
    smallest, largest = extrema
    primary_gap = abs(smallest.primary_optimum_cost - largest.primary_optimum_cost)
    if primary_gap > max(0.1, abs(smallest.primary_optimum_cost) * 1e-6):
        raise RuntimeError("Two joint extrema do not share the same primary cost")
    if smallest.target_accepted_mwh > largest.target_accepted_mwh + 1e-3:
        raise RuntimeError("Joint MILP MWh interval has inverted bounds")
    if any(
        value > specs[target_unit_id].max_mw + 1e-3
        for value in (
            *smallest.target_dispatch_24h,
            *largest.target_dispatch_24h,
        )
    ):
        raise RuntimeError("Extreme target dispatch exceeds technical rating")
    return JointCandidateMwhEnvelope(
        target_unit_id=target_unit_id,
        minimum_accepted_mwh=smallest.target_accepted_mwh,
        maximum_accepted_mwh=largest.target_accepted_mwh,
        minimum_24h_dispatch_mw=smallest.target_dispatch_24h,
        maximum_24h_dispatch_mw=largest.target_dispatch_24h,
        minimum_24h_online=smallest.target_online_24h,
        maximum_24h_online=largest.target_online_24h,
        minimum_primary_cost=smallest.primary_optimum_cost,
        maximum_primary_cost=largest.primary_optimum_cost,
        minimum_schedule_cost=smallest.extreme_total_cost,
        maximum_schedule_cost=largest.extreme_total_cost,
        allowed_primary_cost_increase=max(
            smallest.allowed_cost_increase,
            largest.allowed_cost_increase,
        ),
        terminal_mode=terminal_mode,
        technical_source=technical_source,
        technical_source_description=technical_source_description,
        readiness=readiness,
    )
