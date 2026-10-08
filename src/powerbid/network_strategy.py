"""Network-aware 24h bidding-policy comparisons using a validated DC network.

All prices and rewards in this file are LOCAL LOSSLESS DC COUNTERFACTUALS;
no PMSS bid submission or simulation endpoint is contacted. Physical unit
commitment, reserves, outages, AC losses and actual PMSS settlement are out
of scope. These must not be conflated with the separate unit-commitment MILP.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from math import isfinite

from powerbid.network_dispatch import DcNetwork, DcOffer, dc_clear_hour
from powerbid.pmss_integration import (
    PeriodBid,
    PMSSSnapshot,
    curve_for_period,
)
from powerbid.strategy_lab import BidPolicy, DemandStress, generate_policy_plan, stress_grid
from powerbid.unit_commitment import TerminalMode, ThermalConstraints, audit_dispatch


@dataclass(frozen=True, slots=True)
class NetworkHour:
    period: int
    dispatched_mw: float
    target_lmp: float
    margin: float
    branch_flows_mw: dict[str, float]
    nodal_prices: dict[str, float]


@dataclass(frozen=True, slots=True)
class NetworkDay:
    name: str
    probability: float
    total_margin: float
    accepted_mwh: float
    hours: tuple[NetworkHour, ...]


@dataclass(frozen=True, slots=True)
class NetworkBidResult:
    name: str
    periods: tuple[PeriodBid, ...]
    expected_margin: float
    downside_margin: float
    worst_margin: float
    expected_accepted_mwh: float
    score: float
    scenarios: tuple[NetworkDay, ...]
    model_label: str = "lossless DC nodal surrogate; not PMSS's actual clearing"
    physically_feasible: bool | None = None
    physical_violations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NetworkBidComparison:
    baseline: NetworkBidResult
    recommended: NetworkBidResult
    ranked: tuple[NetworkBidResult, ...]
    evaluated: int


def verify_network_inputs(
    snapshot: PMSSSnapshot, network: DcNetwork, target_unit_id: str
) -> None:
    """Fail closed on provenance or structural disagreement before optimization."""
    units = {unit.unit_id for unit in snapshot.units}
    if target_unit_id not in units:
        raise ValueError("Target PMSS unit is not present in the snapshot")
    if set(network.unit_bus) != units:
        raise ValueError("Network unitBus IDs must exactly match the PMSS generator IDs")
    for period in range(24):
        total = sum(series[period] for series in network.hourly_demand_mw.values())
        expected = snapshot.demand_forecast_mw[period]
        if abs(total - expected) > max(0.1, abs(expected) * 1e-5):
            raise ValueError(
                f"Network nodal demand disagrees with PMSS snapshot in hour {period+1}: "
                f"{total:.5f} versus {expected:.5f} MW"
            )
    if network.demand_source.strip() != snapshot.forecast_source.strip():
        raise ValueError(
            "Nodal loads and PMSS aggregate forecast must name the exact same source"
        )


def _tail(values: Sequence[NetworkDay], portion: float) -> float:
    remaining = portion
    profit = 0.0
    for row in sorted(values, key=lambda x: x.total_margin):
        weight = min(row.probability, remaining)
        profit += row.total_margin * weight
        remaining -= weight
        if remaining <= 1e-12:
            break
    return profit / portion


def evaluate_network_plan(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    target_unit_id: str,
    name: str,
    plan: Sequence[PeriodBid],
    scenarios: Iterable[DemandStress],
    *,
    risk_aversion: float = 0.35,
    tail_fraction: float = 0.25,
) -> NetworkBidResult:
    verify_network_inputs(snapshot, network, target_unit_id)
    if not name.strip():
        raise ValueError("Strategy name cannot be empty")
    if not isfinite(risk_aversion) or not 0 <= risk_aversion <= 1:
        raise ValueError("risk_aversion must be 0..1")
    if not isfinite(tail_fraction) or not 0 < tail_fraction <= 1:
        raise ValueError("tail_fraction must be (0,1]")
    variant = tuple(scenarios)
    if not 1 <= len(variant) <= 9:
        raise ValueError("Provide 1..9 offline scenarios")
    weights = sum(v.probability for v in variant)
    if not isfinite(weights) or weights <= 0:
        raise ValueError("Scenario probabilities are invalid")
    periods = tuple(plan)
    unit = snapshot.unit(target_unit_id)
    if network.unit_bus[target_unit_id] not in network.buses:
        raise ValueError("Target unit bus is unavailable")
    scenario_days: list[NetworkDay] = []
    for stress in variant:
        hours = []
        for period in range(1, 25):
            offers: list[DcOffer] = []
            for peer in snapshot.units:
                blocks = curve_for_period(
                    periods if peer.unit_id == target_unit_id
                    else snapshot.bids[peer.unit_id],
                    period,
                )
                if not 1 <= len(blocks) <= snapshot.limits.max_segments:
                    raise ValueError("Invalid segment count for the selected PMSS market")
                last = 0.0
                for i, seg in enumerate(blocks, 1):
                    if not all(isfinite(v) for v in (
                        seg.start_power, seg.end_power, seg.price
                    )):
                        raise ValueError("Nonfinite segment")
                    if abs(seg.start_power - last) > 1e-6 or seg.end_power <= seg.start_power:
                        raise ValueError("Bid segments must be contiguous and increasing")
                    if seg.price < 0:
                        raise ValueError("Negative offer price not supported by this model")
                    last = seg.end_power
                    offers.append(
                        DcOffer(
                            unit_id=peer.unit_id,
                            block=i,
                            quantity_mw=seg.quantity_mw,
                            price=seg.price * (
                                1.0 if peer.unit_id == target_unit_id
                                else stress.peer_price_factor
                            ),
                        )
                    )
                if last > peer.capacity_mw + 1e-6:
                    raise ValueError("Bid exceeds the mapped unit maximum MW")
            outcome = dc_clear_hour(
                network, offers, period, load_multiplier=stress.demand_factor
            )
            dispatched = outcome.accepted_by_unit[target_unit_id]
            target_lmp = outcome.nodal_prices[network.unit_bus[target_unit_id]]
            # One-hour interval, constant marginal cost proxy, no startup costs.
            margin = (target_lmp - unit.running_cost) * dispatched
            hours.append(
                NetworkHour(
                    period=period,
                    dispatched_mw=dispatched,
                    target_lmp=target_lmp,
                    margin=margin,
                    branch_flows_mw=outcome.line_flows_mw,
                    nodal_prices=outcome.nodal_prices,
                )
            )
        probability = stress.probability / weights
        scenario_days.append(
            NetworkDay(
                name=stress.name,
                probability=probability,
                total_margin=sum(h.margin for h in hours),
                accepted_mwh=sum(h.dispatched_mw for h in hours),
                hours=tuple(hours),
            )
        )
    expected = sum(day.probability * day.total_margin for day in scenario_days)
    downside = _tail(scenario_days, tail_fraction)
    return NetworkBidResult(
        name=name,
        periods=periods,
        expected_margin=expected,
        downside_margin=downside,
        worst_margin=min(day.total_margin for day in scenario_days),
        expected_accepted_mwh=sum(
            day.probability * day.accepted_mwh for day in scenario_days
        ),
        score=(1-risk_aversion)*expected + risk_aversion*downside,
        scenarios=tuple(scenario_days),
    )


def compare_network_policies(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    target_unit_id: str,
    *,
    policies: Sequence[BidPolicy] | None = None,
    scenarios: Iterable[DemandStress] | None = None,
    risk_aversion: float = 0.35,
    tail_fraction: float = 0.25,
    physical: ThermalConstraints | None = None,
    terminal_mode: TerminalMode = "carryover",
) -> NetworkBidComparison:
    """Price-taking simulation comparison with verified nodal topology.

    Best = maximum score *among tested candidates*, not global optimum.
    """
    chosen = tuple(
        policies if policies is not None else (
            BidPolicy("边际成本报价"),
            BidPolicy("固定加价20", markup=20),
            BidPolicy("固定加价50", markup=50),
            BidPolicy("阶梯报价", markup=5, slope=20),
            BidPolicy("负荷自适应报价", markup=10, slope=10, scarcity_sensitivity=100),
        )
    )
    if not 1 <= len(chosen) <= 20:
        raise ValueError("Support 1..20 candidate policies per comparison")
    if len({p.name for p in chosen}) != len(chosen):
        raise ValueError("Strategy names must be unique")
    variants = tuple(stress_grid() if scenarios is None else scenarios)
    if physical is not None and physical.unit_id != target_unit_id:
        raise ValueError("Physical constraints must match target unit ID")
    baseline = evaluate_network_plan(
        snapshot, network, target_unit_id,
        "PMSS 原始已申报曲线（DC模型重算）",
        snapshot.bids[target_unit_id], variants,
        risk_aversion=risk_aversion, tail_fraction=tail_fraction,
    )
    results = [baseline]
    seen = {baseline.periods}
    for policy in chosen:
        plan = generate_policy_plan(snapshot, target_unit_id, policy)
        if plan in seen:
            continue
        seen.add(plan)
        results.append(
            evaluate_network_plan(
                snapshot, network, target_unit_id,
                policy.name, plan, variants,
                risk_aversion=risk_aversion, tail_fraction=tail_fraction,
            )
        )
    if physical is not None:
        checked: list[NetworkBidResult] = []
        for result in results:
            issues = []
            for day in result.scenarios:
                audit = audit_dispatch(
                    physical,
                    [hour.dispatched_mw for hour in day.hours],
                    terminal_mode=terminal_mode,
                )
                if not audit.feasible:
                    issues.extend(
                        f"{day.name}: {error}"
                        for error in audit.violations[:4]
                    )
            checked.append(
                replace(
                    result,
                    physically_feasible=not issues,
                    physical_violations=tuple(issues[:8]),
                )
            )
        results = checked
        baseline = results[0]
    ranked = tuple(
        sorted(
            results,
            key=lambda x: (
                x.physically_feasible is not False,
                x.score,
                x.expected_margin,
            ),
            reverse=True,
        )
    )
    if physical is not None and not any(r.physically_feasible for r in ranked):
        raise ValueError("No candidate passed every 24h physical screening scenario")
    return NetworkBidComparison(
        baseline=baseline,
        recommended=ranked[0],
        ranked=ranked,
        evaluated=len(results),
    )
