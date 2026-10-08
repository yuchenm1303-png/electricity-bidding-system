"""Independent PMSS-compatible bidding policies and scenario risk comparison.

Offline single-zone surrogate ONLY. The PMSS adapter is never invoked, and no
market bid is submitted. Network, commitment, ramp, startup and actual PMSS
settlement are deliberately out of scope until data and rules are verified.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import isfinite

from powerbid.clearing.uniform_price import UniformPriceClearingEngine
from powerbid.models import MarketScenario, Offer
from powerbid.pmss_integration import (
    BidSegment,
    GeneratorSpec,
    PeriodBid,
    PMSSSnapshot,
    curve_for_period,
)


@dataclass(frozen=True, slots=True)
class BidPolicy:
    """A transparent, deterministic rule for generating supply curves."""

    name: str
    markup: float = 0.0
    slope: float = 0.0
    scarcity_sensitivity: float = 0.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Policy name is required")
        for value in (self.markup, self.slope, self.scarcity_sensitivity):
            if not isfinite(value) or value < 0:
                raise ValueError("Policy parameters must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class DemandStress:
    """Synthetic demand and peer-price multipliers; NOT forecast probabilities."""

    name: str
    demand_factor: float = 1.0
    peer_price_factor: float = 1.0
    probability: float = 1.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Scenario name is required")
        if any(
            not isfinite(value) or value <= 0
            for value in (self.demand_factor, self.peer_price_factor, self.probability)
        ):
            raise ValueError("Scenario factors and weights must be finite and positive")


@dataclass(frozen=True, slots=True)
class HourlyOutcome:
    period: int
    clearing_price: float | None
    accepted_mw: float
    profit: float
    feasible: bool


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    name: str
    probability: float
    total_profit: float
    accepted_mwh: float
    feasible: bool
    hours: tuple[HourlyOutcome, ...]


@dataclass(frozen=True, slots=True)
class StrategyResult:
    name: str
    periods: tuple[PeriodBid, ...]
    expected_profit: float
    downside_profit: float
    worst_profit: float
    expected_accepted_mwh: float
    feasible_probability: float
    score: float
    scenarios: tuple[ScenarioOutcome, ...]


@dataclass(frozen=True, slots=True)
class StrategyComparison:
    baseline: StrategyResult
    recommended: StrategyResult
    ranked: tuple[StrategyResult, ...]
    evaluated: int
    risk_aversion: float
    tail_fraction: float


def stress_grid(
    *,
    demand_deviation: float = 0.05,
    peer_price_deviation: float = 0.05,
) -> tuple[DemandStress, ...]:
    """Equal-weight, explicitly synthetic 3 x 3 sensitivity scenarios."""
    if any(
        not isfinite(value) or value < 0 or value >= 1
        for value in (demand_deviation, peer_price_deviation)
    ):
        raise ValueError("Stress deviations must be between zero and one")
    cases: list[DemandStress] = []
    for demand in sorted({1.0 - demand_deviation, 1.0, 1.0 + demand_deviation}):
        for price in sorted({1.0 - peer_price_deviation, 1.0, 1.0 + peer_price_deviation}):
            cases.append(
                DemandStress(
                    name=f"demand x{demand:.2f} / peer bid x{price:.2f}",
                    demand_factor=demand,
                    peer_price_factor=price,
                )
            )
    return tuple(cases)


def _boundaries(unit: GeneratorSpec, segments: int) -> tuple[float, ...]:
    """Put technical minimum at an offer breakpoint, not a dispatch constraint."""
    capacity = unit.capacity_mw
    if not isfinite(capacity) or capacity <= 0 or not 1 <= segments <= 5:
        raise ValueError("Invalid unit capacity or number of bid segments")
    if not 0 <= unit.min_power_mw <= capacity:
        raise ValueError("Invalid technical minimum")
    if segments == 1:
        return (0.0, capacity)
    if 0 < unit.min_power_mw < capacity:
        remaining = capacity - unit.min_power_mw
        return (0.0, unit.min_power_mw) + tuple(
            unit.min_power_mw + remaining * k / (segments - 1)
            for k in range(1, segments)
        )
    return tuple(capacity * k / segments for k in range(segments + 1))


def generate_policy_plan(
    snapshot: PMSSSnapshot, target_unit_id: str, policy: BidPolicy
) -> tuple[PeriodBid, ...]:
    """Generate valid five-band curves; honor PMSS's same-curve setting.

    Min-power is used as a band boundary only. It DOES NOT guarantee that a
    dispatch will satisfy commitment, min up/down time or ramp constraints.
    """
    unit = snapshot.unit(target_unit_id)
    n = min(snapshot.limits.max_segments, 5)
    edges = _boundaries(unit, n)
    total_capacity = sum(u.capacity_mw for u in snapshot.units)
    if total_capacity <= 0:
        raise ValueError("Total market capacity must be positive")

    def curve(demand: float) -> tuple[BidSegment, ...]:
        scarcity = max(0.0, demand / total_capacity - 0.7)
        uplift = policy.scarcity_sensitivity * scarcity
        return tuple(
            BidSegment(
                round(edges[i], 8),
                round(edges[i + 1], 8),
                round(unit.running_cost + policy.markup + policy.slope * i + uplift, 8),
            )
            for i in range(n)
        )

    if snapshot.limits.same_curve:
        # Only information in the *forecast* is used to set a common curve.
        return (PeriodBid(1, snapshot.period_num, curve(max(snapshot.demand_forecast_mw))),)
    return tuple(
        PeriodBid(hour, hour, curve(load))
        for hour, load in enumerate(snapshot.demand_forecast_mw, 1)
    )


def _validate_plan(
    snapshot: PMSSSnapshot, target_unit_id: str, periods: Sequence[PeriodBid]
) -> None:
    if target_unit_id not in snapshot.bids:
        raise ValueError("Target unit does not belong to snapshot")
    unit = snapshot.unit(target_unit_id)
    for hour in range(1, snapshot.period_num + 1):
        blocks = curve_for_period(tuple(periods), hour)
        if not 1 <= len(blocks) <= snapshot.limits.max_segments:
            raise ValueError("Too many or too few bid segments")
        last = 0.0
        for block in blocks:
            if any(not isfinite(v) for v in (block.start_power, block.end_power, block.price)):
                raise ValueError("Non-finite price or quantity")
            if abs(block.start_power - last) > 1e-6 or block.end_power <= block.start_power:
                raise ValueError("Non-contiguous power segments")
            if block.price < 0:
                raise ValueError("Negative supply price not supported by this surrogate")
            last = block.end_power
        if last > unit.capacity_mw + 1e-6:
            raise ValueError("Bid exceeds known unit capacity")
        # Deliberately do not reject historical prices outside PMSS rule bounds:
        # the platform's actual validation has not been fully confirmed.


def simulate_strategy(
    snapshot: PMSSSnapshot,
    target_unit_id: str,
    periods: Sequence[PeriodBid],
    stress: DemandStress,
) -> tuple[HourlyOutcome, ...]:
    """Reclear each hour using the local uniform-price single-zone engine."""
    _validate_plan(snapshot, target_unit_id, periods)
    engine = UniformPriceClearingEngine()
    rows: list[HourlyOutcome] = []
    period_bids = tuple(periods)
    for period, forecast_load in enumerate(snapshot.demand_forecast_mw, 1):
        offers: list[Offer] = []
        target_keys: list[str] = []
        for unit in snapshot.units:
            blocks = (
                curve_for_period(period_bids, period)
                if unit.unit_id == target_unit_id
                else curve_for_period(snapshot.bids[unit.unit_id], period)
            )
            for block_index, block in enumerate(blocks):
                ident = f"{unit.unit_id}::block{block_index}"
                offers.append(
                    Offer(
                        unit_id=ident,
                        quantity_mw=block.quantity_mw,
                        bid_price=block.price * (
                            1.0 if unit.unit_id == target_unit_id else stress.peer_price_factor
                        ),
                        marginal_cost=unit.running_cost,
                    )
                )
                if unit.unit_id == target_unit_id:
                    target_keys.append(ident)
        clearing = engine.clear(
            MarketScenario(
                name=f"offline scenario / hour {period}",
                demand_mw=forecast_load * stress.demand_factor,
                interval_hours=1.0,
                target_unit_id=target_keys[0],
                offers=tuple(offers),
                data_source="synthetic",
            )
        )
        accepted = sum(clearing.accepted_mw.get(ident, 0.0) for ident in target_keys)
        clearing_price = clearing.clearing_price
        profit = (
            0.0 if clearing_price is None
            else (clearing_price - snapshot.unit(target_unit_id).running_cost) * accepted
        )
        rows.append(
            HourlyOutcome(
                period=period,
                clearing_price=clearing_price,
                accepted_mw=accepted,
                profit=profit,
                feasible=clearing.feasible,
            )
        )
    return tuple(rows)


def _lower_tail(values: Sequence[ScenarioOutcome], fraction: float) -> float:
    """Probability-weighted average profit of the worst fraction of days."""
    remaining = fraction
    total = 0.0
    for outcome in sorted(values, key=lambda v: v.total_profit):
        mass = min(remaining, outcome.probability)
        total += mass * outcome.total_profit
        remaining -= mass
        if remaining <= 1e-12:
            break
    return total / fraction


def evaluate_strategy(
    snapshot: PMSSSnapshot,
    target_unit_id: str,
    name: str,
    periods: Sequence[PeriodBid],
    scenarios: Iterable[DemandStress],
    *,
    risk_aversion: float = 0.35,
    tail_fraction: float = 0.25,
) -> StrategyResult:
    if not isfinite(risk_aversion) or not 0 <= risk_aversion <= 1:
        raise ValueError("risk_aversion must be between 0 and 1")
    if not isfinite(tail_fraction) or not 0 < tail_fraction <= 1:
        raise ValueError("tail_fraction must be within (0, 1]")
    if not name.strip():
        raise ValueError("Strategy name is required")
    variants = tuple(scenarios)
    if not variants:
        raise ValueError("At least one scenario is needed")
    total_probability = sum(v.probability for v in variants)
    if not isfinite(total_probability) or total_probability <= 0:
        raise ValueError("Invalid scenario weights")
    outcomes: list[ScenarioOutcome] = []
    for stress in variants:
        hours = simulate_strategy(snapshot, target_unit_id, periods, stress)
        outcomes.append(
            ScenarioOutcome(
                name=stress.name,
                probability=stress.probability / total_probability,
                total_profit=sum(h.profit for h in hours),
                accepted_mwh=sum(h.accepted_mw for h in hours),
                feasible=all(h.feasible for h in hours),
                hours=hours,
            )
        )
    expected = sum(v.probability * v.total_profit for v in outcomes)
    downside = _lower_tail(outcomes, tail_fraction)
    return StrategyResult(
        name=name,
        periods=tuple(periods),
        expected_profit=expected,
        downside_profit=downside,
        worst_profit=min(v.total_profit for v in outcomes),
        expected_accepted_mwh=sum(v.probability * v.accepted_mwh for v in outcomes),
        feasible_probability=sum(v.probability for v in outcomes if v.feasible),
        score=(1 - risk_aversion) * expected + risk_aversion * downside,
        scenarios=tuple(outcomes),
    )


def compare_strategies(
    snapshot: PMSSSnapshot,
    target_unit_id: str,
    *,
    markups: Sequence[float] = (0.0, 20.0, 50.0, 100.0),
    scenarios: Iterable[DemandStress] | None = None,
    risk_aversion: float = 0.35,
    tail_fraction: float = 0.25,
) -> StrategyComparison:
    """Compare the recorded curve, flat markup, progressive, adaptive policies.

    All results are offline estimates, not observed PMSS clearing. Only plans
    feasible in EVERY stress scenario can be recommended.
    """
    variants = tuple(stress_grid() if scenarios is None else scenarios)
    prices = sorted(set(float(v) for v in markups))
    if not prices or len(prices) > 20:
        raise ValueError("Provide between one and twenty markup values")
    if any(not isfinite(price) or price < 0 for price in prices):
        raise ValueError("Markups must be finite and non-negative")

    original = snapshot.bids[target_unit_id]
    baseline = evaluate_strategy(
        snapshot, target_unit_id, "平台已有报价（本地复算）", original, variants,
        risk_aversion=risk_aversion, tail_fraction=tail_fraction,
    )
    evaluated = [baseline]
    for markup in prices:
        policies = (
            BidPolicy(name=f"固定加价 +{markup:g}", markup=markup),
            BidPolicy(name=f"分段递增加价 +{markup:g}", markup=markup, slope=max(5.0, markup / 3)),
            BidPolicy(
                name=f"负荷自适应 +{markup:g}",
                markup=markup,
                slope=max(5.0, markup / 4),
                scarcity_sensitivity=max(40.0, markup * 2),
            ),
        )
        for policy in policies:
            plan = generate_policy_plan(snapshot, target_unit_id, policy)
            evaluated.append(
                evaluate_strategy(
                    snapshot, target_unit_id, policy.name, plan, variants,
                    risk_aversion=risk_aversion, tail_fraction=tail_fraction,
                )
            )
    ranked = tuple(
        sorted(
            evaluated,
            key=lambda item: (item.feasible_probability >= 1 - 1e-12,
                              item.score, item.expected_profit),
            reverse=True,
        )
    )
    safe = [result for result in ranked if result.feasible_probability >= 1 - 1e-12]
    if not safe:
        raise ValueError("No plan serves every stress scenario in the offline model")
    return StrategyComparison(
        baseline=baseline,
        recommended=safe[0],
        ranked=ranked,
        evaluated=len(evaluated),
        risk_aversion=risk_aversion,
        tail_fraction=tail_fraction,
    )
