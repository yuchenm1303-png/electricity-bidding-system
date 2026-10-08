"""Risk-aware bid comparisons using the integrated 24h DC+unit-commitment MILP.

Candidate prices, nodal prices and profit are ALL offline simplifications.
Bidding decisions alter dispatch and nodal prices in the joint model, unlike
a fixed forecast-price self-scheduling calculation. No PMSS I/O occurs here.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import isfinite

from powerbid.joint_market import JointMarketResult, joint_clear_day
from powerbid.network_dispatch import DcNetwork
from powerbid.pmss_integration import PeriodBid, PMSSSnapshot
from powerbid.strategy_lab import BidPolicy, DemandStress, generate_policy_plan
from powerbid.unit_commitment import TerminalMode, ThermalConstraints


@dataclass(frozen=True, slots=True)
class JointBidScenario:
    name: str
    probability: float
    energy_margin: float
    target_transition_cost: float
    net_profit_proxy: float
    accepted_mwh: float
    market: JointMarketResult


@dataclass(frozen=True, slots=True)
class JointBidEvaluation:
    name: str
    periods: tuple[PeriodBid, ...]
    expected_net_profit: float
    downside_net_profit: float
    worst_net_profit: float
    expected_accepted_mwh: float
    risk_score: float
    scenarios: tuple[JointBidScenario, ...]
    model_label: str = "integrated DC-UC profit proxy; NOT observed PMSS profit"


@dataclass(frozen=True, slots=True)
class JointBidComparison:
    baseline: JointBidEvaluation
    recommended: JointBidEvaluation
    ranked: tuple[JointBidEvaluation, ...]
    evaluated: int
    risk_aversion: float
    tail_fraction: float


def _tail(values: Sequence[JointBidScenario], fraction: float) -> float:
    remaining = fraction
    total = 0.0
    for item in sorted(values, key=lambda x: x.net_profit_proxy):
        weight = min(remaining, item.probability)
        total += weight * item.net_profit_proxy
        remaining -= weight
        if remaining <= 1e-12:
            break
    return total / fraction


def evaluate_joint_bid(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    technical: dict[str, ThermalConstraints],
    target_unit_id: str,
    name: str,
    periods: Sequence[PeriodBid],
    scenarios: Iterable[DemandStress],
    *,
    risk_aversion: float = 0.35,
    tail_fraction: float = 0.25,
    terminal_mode: TerminalMode = "complete",
    solver_time_limit_seconds: float = 25.0,
) -> JointBidEvaluation:
    """Evaluate each 24-hour synthetic stress in the integrated market model."""
    if not name.strip():
        raise ValueError("Strategy name is required")
    if not isfinite(risk_aversion) or not 0 <= risk_aversion <= 1:
        raise ValueError("risk_aversion must be between zero and one")
    if not isfinite(tail_fraction) or not 0 < tail_fraction <= 1:
        raise ValueError("tail_fraction must be within (0,1]")
    variants = tuple(scenarios)
    if not 1 <= len(variants) <= 3:
        raise ValueError("Provide between one and three explicitly synthetic scenarios")
    mass = sum(v.probability for v in variants)
    if not isfinite(mass) or mass <= 0:
        raise ValueError("Scenario weights must be finite and positive")
    unit = snapshot.unit(target_unit_id)
    spec = technical[target_unit_id]
    target_bus = network.unit_bus[target_unit_id]
    evaluated: list[JointBidScenario] = []
    for stress in variants:
        market = joint_clear_day(
            snapshot,
            network,
            technical,
            target_unit_id,
            candidate_plan=periods,
            demand_multiplier=stress.demand_factor,
            peer_bid_multiplier=stress.peer_price_factor,
            terminal_mode=terminal_mode,
            time_limit_seconds=solver_time_limit_seconds,
        )
        gross = sum(
            (hour.nodal_prices[target_bus] - unit.running_cost)
            * hour.accepted_by_unit[target_unit_id]
            for hour in market.hours
        )
        transition_cost = sum(
            spec.startup_cost * hour.unit_started[target_unit_id]
            + spec.shutdown_cost * hour.unit_stopped[target_unit_id]
            for hour in market.hours
        )
        evaluated.append(
            JointBidScenario(
                name=stress.name,
                probability=stress.probability / mass,
                energy_margin=gross,
                target_transition_cost=transition_cost,
                net_profit_proxy=gross - transition_cost,
                accepted_mwh=sum(
                    hour.accepted_by_unit[target_unit_id]
                    for hour in market.hours
                ),
                market=market,
            )
        )
    mean_profit = sum(x.probability * x.net_profit_proxy for x in evaluated)
    downside = _tail(evaluated, tail_fraction)
    return JointBidEvaluation(
        name=name,
        periods=tuple(periods),
        expected_net_profit=mean_profit,
        downside_net_profit=downside,
        worst_net_profit=min(x.net_profit_proxy for x in evaluated),
        expected_accepted_mwh=sum(
            x.probability * x.accepted_mwh for x in evaluated
        ),
        risk_score=(1.0-risk_aversion)*mean_profit + risk_aversion*downside,
        scenarios=tuple(evaluated),
    )


def compare_joint_bids(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    technical: dict[str, ThermalConstraints],
    target_unit_id: str,
    *,
    policies: Sequence[BidPolicy] | None = None,
    scenarios: Iterable[DemandStress] | None = None,
    risk_aversion: float = 0.35,
    tail_fraction: float = 0.25,
    terminal_mode: TerminalMode = "complete",
    solver_time_limit_seconds: float = 25.0,
) -> JointBidComparison:
    """Choose highest risk-adjusted tested bid; never call it global optimum.

    Raises on any infeasible stress, rather than silently assigning a zero
    profit or conflating unserved demand with feasible bidding outcomes.
    """
    chosen = tuple(
        policies if policies is not None else (
            BidPolicy("边际成本", markup=0),
            BidPolicy("固定加价20", markup=20),
            BidPolicy("阶梯报价", markup=5, slope=15),
            BidPolicy("紧张时段溢价", markup=10, slope=10, scarcity_sensitivity=100),
        )
    )
    if not 1 <= len(chosen) <= 6:
        raise ValueError("Support one to six policies per joint MILP comparison")
    if len(set(p.name for p in chosen)) != len(chosen):
        raise ValueError("Duplicate policy names")
    variants = tuple(
        (DemandStress("neutral", 1.0, 1.0),)
        if scenarios is None else scenarios
    )
    baseline = evaluate_joint_bid(
        snapshot, network, technical, target_unit_id,
        "PMSS 已申报基线（联合模型重算）",
        snapshot.bids[target_unit_id], variants,
        risk_aversion=risk_aversion,
        tail_fraction=tail_fraction,
        terminal_mode=terminal_mode,
        solver_time_limit_seconds=solver_time_limit_seconds,
    )
    results = [baseline]
    seen = {baseline.periods}
    for policy in chosen:
        proposal = generate_policy_plan(snapshot, target_unit_id, policy)
        if proposal in seen:
            continue
        seen.add(proposal)
        results.append(
            evaluate_joint_bid(
                snapshot, network, technical, target_unit_id,
                policy.name, proposal, variants,
                risk_aversion=risk_aversion,
                tail_fraction=tail_fraction,
                terminal_mode=terminal_mode,
                solver_time_limit_seconds=solver_time_limit_seconds,
            )
        )
    ranked = tuple(
        sorted(
            results,
            key=lambda value: (
                value.risk_score, value.expected_net_profit
            ),
            reverse=True,
        )
    )
    return JointBidComparison(
        baseline=baseline,
        recommended=ranked[0],
        ranked=ranked,
        evaluated=len(results),
        risk_aversion=risk_aversion,
        tail_fraction=tail_fraction,
    )
