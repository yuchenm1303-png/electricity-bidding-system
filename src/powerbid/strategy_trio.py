"""Three traceable bid *research* profiles built on the existing DC and DC+UC solvers.

No PMSS execution, submission, or independent physical-parameter verification.
A 24h constant five-block curve is an offer, NOT a predicted generator schedule.
Missing thermal records keep dispatch feasibility UNKNOWN rather than inferred.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

from powerbid.joint_market import JointInfeasibleError
from powerbid.joint_strategy import evaluate_joint_bid
from powerbid.network_dispatch import DcNetwork
from powerbid.network_strategy import NetworkBidResult, evaluate_network_plan, verify_network_inputs
from powerbid.pmss_bid_rule_safety import validate_new_curve
from powerbid.pmss_integration import PeriodBid, PMSSSnapshot, curve_for_period
from powerbid.strategy_lab import BidPolicy, DemandStress, generate_policy_plan
from powerbid.unit_commitment import TerminalMode, ThermalConstraints


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    profile: str
    policy_name: str
    periods: tuple[PeriodBid, ...]
    expected_dc_margin: float
    downside_dc_margin: float
    worst_dc_margin: float
    expected_dc_mwh: float
    profile_score: float
    price_blocks: tuple[tuple[float, float, float], ...]
    neutral_dc_dispatch_mw: tuple[float, ...]
    full_capacity_dc_hours: int
    physical_status: str
    integrated_net_profit: float | None
    integrated_dispatch_mw: tuple[float, ...] | None
    startup_shutdown_cost: float | None
    local_candidate_usable: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyTrio:
    target_unit_id: str
    candidates: tuple[StrategyCandidate, ...]
    policies_screened: int
    synthetic_scenarios: tuple[str, ...]
    missing_physical_unit_ids: tuple[str, ...]
    model: str = "local lossless DC sensitivity + optional 24h DC/UC MILP"
    physical_inputs_independently_verified: bool = False
    real_pmss_clearing: bool = False
    safe_for_live_submission: bool = False
    disclaimer: str = (
        "DC dual prices and profits are local proxies, not PMSS settlement. "
        "Stress weights are equal research sensitivities, not probabilities. "
        "Complete source-attested UC inputs certify neither actual PMSS rules "
        "nor future demand or a proven real-world profit optimum."
    )


def _legal_plans(snapshot: PMSSSnapshot, target_unit_id: str) -> tuple[
    tuple[str, tuple[PeriodBid, ...]], ...
]:
    unit = snapshot.unit(target_unit_id)
    floor = snapshot.limits.price_floor
    ceiling = snapshot.limits.price_ceiling
    lower = max(unit.running_cost, 0.0, floor if floor is not None else 0.0)
    upper = min(10000.0, ceiling if ceiling is not None else 10000.0)
    if not isfinite(lower) or not isfinite(upper) or upper <= lower + 1e-8:
        raise ValueError("Current price ceiling leaves no room for three cost-covering strategies")
    scale = min(upper - lower, max(50.0, unit.running_cost * 0.5))
    proposals: list[tuple[str, tuple[PeriodBid, ...]]] = []
    seen: set[tuple[PeriodBid, ...]] = set()
    # Changing bid markup changes a real candidate; do not silently clamp
    # an otherwise illegal tariff to the market ceiling.
    for fraction, slope_fraction in (
        (0.0, 0.0), (0.10, 0.0), (0.25, 0.0),
        (0.50, 0.0), (0.75, 0.0), (1.0, 0.0),
        (0.10, 0.05), (0.35, 0.05),
    ):
        policy = BidPolicy(
            name=f"cost_plus_{fraction:.2f}_ladder_{slope_fraction:.2f}",
            markup=round(lower - unit.running_cost + fraction * scale, 8),
            slope=round(slope_fraction * scale, 8),
        )
        plan = generate_policy_plan(snapshot, target_unit_id, policy)
        try:
            for period in plan:
                validate_new_curve(snapshot, target_unit_id, period.segments)
        except ValueError:
            continue
        if plan in seen:
            continue
        # An all-zero curve with zero/missing cost is not a robust recommendation.
        if all(abs(block.price) <= 1e-9 for bid in plan for block in bid.segments):
            continue
        seen.add(plan)
        proposals.append((policy.name, plan))
    if len(proposals) < 3:
        raise ValueError("Fewer than three distinct legal, nonzero, cost-covering curves")
    return tuple(proposals)


def _rank(result: NetworkBidResult, profile: str) -> float:
    if profile == "收益优先":
        return result.expected_margin
    if profile == "均衡":
        return 0.55 * result.expected_margin + 0.45 * result.downside_margin
    return 0.10 * result.expected_margin + 0.90 * result.downside_margin


def recommend_strategy_trio(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    target_unit_id: str,
    *,
    technical: Mapping[str, ThermalConstraints] | None = None,
    peer_price_deviation: float = 0.05,
    terminal_mode: TerminalMode = "carryover",
    solver_time_limit_seconds: float = 12.0,
) -> StrategyTrio:
    """Screen distinct legal cost-based offers on the actual supplied DC grid.

    A complete UC record unlocks a second *local* joint-MILP check per chosen
    profile. Missing parameters never get estimates. The optional local MILP
    is not evidence of teacher-platform bid acceptance or clearing.
    """
    verify_network_inputs(snapshot, network, target_unit_id)
    if snapshot.limits.market_type != "DA" or snapshot.period_num != 24:
        raise ValueError("Only 24-hour PMSS day-ahead research is supported")
    if snapshot.limits.max_segments > 5:
        raise ValueError("Unsupported PMSS segment count")
    if len(network.buses) > 60 or len(network.lines) > 90 or len(snapshot.units) > 30:
        raise ValueError("Online strategy screening grid exceeds resource limits")
    if (type(peer_price_deviation) not in (float, int)
            or not isfinite(peer_price_deviation)
            or not 0 <= peer_price_deviation <= 0.15):
        raise ValueError("Peer price deviation must be finite and within 0..15%")
    if terminal_mode not in ("carryover", "complete"):
        raise ValueError("Unknown terminal mode")
    if (type(solver_time_limit_seconds) not in (int, float)
            or not isfinite(solver_time_limit_seconds)
            or not 1 <= solver_time_limit_seconds <= 30):
        raise ValueError("Solver limit must be between 1 and 30 seconds")

    units = {unit.unit_id for unit in snapshot.units}
    if technical is not None:
        if set(technical) != units or any(
            not isinstance(spec, ThermalConstraints) or spec.unit_id != uid
            for uid, spec in technical.items()
        ):
            raise ValueError("Every generator must have an exact thermal record")
    missing = tuple(sorted(units)) if technical is None else ()

    scenarios = tuple(
        DemandStress(
            name=f"synthetic_peer_x{factor:.3f}",
            peer_price_factor=factor,
        )
        for factor in (1 - peer_price_deviation, 1.0, 1 + peer_price_deviation)
    )
    proposals = _legal_plans(snapshot, target_unit_id)
    evaluated = tuple(
        evaluate_network_plan(
            snapshot, network, target_unit_id, name, plan, scenarios,
            risk_aversion=0.5, tail_fraction=1 / 3,
        )
        for name, plan in proposals
    )
    capacity = snapshot.unit(target_unit_id).capacity_mw
    tol = max(1e-5, capacity * 1e-5)

    def full_hours(result: NetworkBidResult) -> int:
        neutral = result.scenarios[1]
        return sum(
            h.dispatched_mw >= capacity - tol for h in neutral.hours
        )

    # Prefer unsaturated policies if their score is tied; never turn a
    # persistently full unverified schedule into a confident recommendation.
    selected: list[tuple[str, NetworkBidResult, float]] = []
    used: set[tuple[PeriodBid, ...]] = set()
    for profile in ("收益优先", "均衡", "稳健"):
        options = [result for result in evaluated if result.periods not in used]
        ranked = sorted(
            options,
            key=lambda result: (
                full_hours(result) != 24,
                _rank(result, profile),
                result.downside_margin,
                -max(b.price for b in curve_for_period(result.periods, 1)),
            ),
            reverse=True,
        )
        winner = ranked[0]
        used.add(winner.periods)
        selected.append((profile, winner, _rank(winner, profile)))

    candidates: list[StrategyCandidate] = []
    for profile, result, score in selected:
        dispatch = tuple(h.dispatched_mw for h in result.scenarios[1].hours)
        saturation = full_hours(result)
        warnings: list[str] = []
        if saturation == 24:
            warnings.append(
                "DC simulator dispatches at maximum MW in all 24 hours; "
                "do not treat a flat full-load curve as a reliable prediction"
            )
        if technical is None:
            warnings.append(
                "Missing complete unit-specific start/stop, ramp, Pmin/Pmax, "
                "minimum on/off and initial-state evidence: physical feasibility UNKNOWN"
            )
        status = "UNKNOWN_MISSING_TECHNICAL_INPUTS"
        net_profit = None
        physical_dispatch = None
        transition_cost = None
        if technical is not None:
            try:
                joint = evaluate_joint_bid(
                    snapshot, network, dict(technical), target_unit_id,
                    result.name, result.periods,
                    (DemandStress("neutral_synthetic"),),
                    tail_fraction=1.0,
                    terminal_mode=terminal_mode,
                    solver_time_limit_seconds=solver_time_limit_seconds,
                )
                net_profit = joint.expected_net_profit
                physical_dispatch = tuple(
                    h.accepted_by_unit[target_unit_id]
                    for h in joint.scenarios[0].market.hours
                )
                transition_cost = joint.scenarios[0].target_transition_cost
                status = "LOCAL_DC_UC_FEASIBLE"
                if all(mw >= technical[target_unit_id].max_mw - tol for mw in physical_dispatch):
                    status = "LOCAL_DC_UC_FULL_OUTPUT_REVIEW"
                    warnings.append(
                        "Even the integrated local model dispatches full output all day; "
                        "requires explicit human review"
                    )
            except JointInfeasibleError:
                status = "LOCAL_DC_UC_INFEASIBLE"
                warnings.append(
                    "This candidate violates the combined local 24h grid/UC constraints"
                )
            except RuntimeError:
                status = "LOCAL_DC_UC_NOT_PROVEN"
                warnings.append(
                    "MILP optimality/feasibility was not proven; no fallback dispatch assumed"
                )
        candidates.append(StrategyCandidate(
            profile=profile,
            policy_name=result.name,
            periods=result.periods,
            expected_dc_margin=result.expected_margin,
            downside_dc_margin=result.downside_margin,
            worst_dc_margin=result.worst_margin,
            expected_dc_mwh=result.expected_accepted_mwh,
            profile_score=score,
            price_blocks=tuple(
                (b.start_power, b.end_power, b.price)
                for b in curve_for_period(result.periods, 1)
            ),
            neutral_dc_dispatch_mw=dispatch,
            full_capacity_dc_hours=saturation,
            physical_status=status,
            integrated_net_profit=net_profit,
            integrated_dispatch_mw=physical_dispatch,
            startup_shutdown_cost=transition_cost,
            local_candidate_usable=(status == "LOCAL_DC_UC_FEASIBLE" and saturation != 24),
            warnings=tuple(warnings),
        ))
    return StrategyTrio(
        target_unit_id=target_unit_id,
        candidates=tuple(candidates),
        policies_screened=len(evaluated),
        synthetic_scenarios=tuple(stress.name for stress in scenarios),
        missing_physical_unit_ids=missing,
    )
