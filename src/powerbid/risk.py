from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from powerbid.clearing.base import ClearingEngine
from powerbid.models import MarketScenario
from powerbid.settlement import settle_offer


@dataclass(frozen=True, slots=True)
class WeightedScenario:
    """One possible market state and its relative probability."""

    name: str
    scenario: MarketScenario
    probability: float = 1.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("scenario name must not be empty")
        if self.probability <= 0:
            raise ValueError("scenario probability must be positive")


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    name: str
    probability: float
    profit: float
    accepted_mw: float
    clearing_price: float | None
    feasible: bool


@dataclass(frozen=True, slots=True)
class RiskBidTrial:
    bid_price: float
    expected_profit: float
    downside_profit: float
    worst_profit: float
    expected_accepted_mw: float
    feasible_probability: float
    score: float
    outcomes: tuple[ScenarioOutcome, ...]


@dataclass(frozen=True, slots=True)
class RiskOptimizationResult:
    target_unit_id: str
    risk_aversion: float
    tail_fraction: float
    best: RiskBidTrial
    trials: tuple[RiskBidTrial, ...]


class RiskAwareBidOptimizer:
    """Optimize one bid across several possible market states.

    ``risk_aversion=0`` maximizes expected profit.
    ``risk_aversion=1`` maximizes lower-tail (CVaR-like) profit.
    Values in between blend the two, keeping the result easy to explain.
    """

    def __init__(
        self,
        engine: ClearingEngine,
        *,
        risk_aversion: float = 0.35,
        tail_fraction: float = 0.25,
        min_feasible_probability: float = 1.0,
    ) -> None:
        if not 0 <= risk_aversion <= 1:
            raise ValueError("risk_aversion must be between 0 and 1")
        if not 0 < tail_fraction <= 1:
            raise ValueError("tail_fraction must be in (0, 1]")
        if not 0 <= min_feasible_probability <= 1:
            raise ValueError("min_feasible_probability must be between 0 and 1")
        self.engine = engine
        self.risk_aversion = float(risk_aversion)
        self.tail_fraction = float(tail_fraction)
        self.min_feasible_probability = float(min_feasible_probability)

    def optimize(
        self,
        scenarios: Iterable[WeightedScenario],
        candidate_prices: Iterable[float],
    ) -> RiskOptimizationResult:
        variants = tuple(scenarios)
        if not variants:
            raise ValueError("at least one market scenario is required")

        total_probability = sum(item.probability for item in variants)
        weights = tuple(item.probability / total_probability for item in variants)

        target_unit_id = variants[0].scenario.target_unit_id
        for item in variants:
            if item.scenario.target_unit_id != target_unit_id:
                raise ValueError("all scenarios must use the same target_unit_id")
            item.scenario.get_offer(target_unit_id)

        prices = sorted({float(price) for price in candidate_prices})
        if not prices:
            raise ValueError("candidate_prices must not be empty")
        if any(price < 0 for price in prices):
            raise ValueError("candidate prices must be non-negative")

        trials: list[RiskBidTrial] = []
        for bid_price in prices:
            outcomes: list[ScenarioOutcome] = []
            for item, probability in zip(variants, weights, strict=True):
                scenario = item.scenario
                target = scenario.get_offer(target_unit_id)
                trial_offer = target.with_bid(bid_price)
                trial_scenario = scenario.replace_offer(target_unit_id, trial_offer)
                clearing = self.engine.clear(trial_scenario)
                settlement = settle_offer(trial_offer, clearing, scenario.interval_hours)
                outcomes.append(
                    ScenarioOutcome(
                        name=item.name,
                        probability=probability,
                        profit=settlement.profit,
                        accepted_mw=settlement.accepted_mw,
                        clearing_price=clearing.clearing_price,
                        feasible=clearing.feasible,
                    )
                )

            expected_profit = sum(item.probability * item.profit for item in outcomes)
            downside_profit = weighted_lower_tail_profit(outcomes, self.tail_fraction)
            worst_profit = min(item.profit for item in outcomes)
            expected_accepted_mw = sum(
                item.probability * item.accepted_mw for item in outcomes
            )
            feasible_probability = sum(
                item.probability for item in outcomes if item.feasible
            )
            score = (
                (1.0 - self.risk_aversion) * expected_profit
                + self.risk_aversion * downside_profit
            )
            trials.append(
                RiskBidTrial(
                    bid_price=bid_price,
                    expected_profit=expected_profit,
                    downside_profit=downside_profit,
                    worst_profit=worst_profit,
                    expected_accepted_mw=expected_accepted_mw,
                    feasible_probability=feasible_probability,
                    score=score,
                    outcomes=tuple(outcomes),
                )
            )

        eligible = [
            trial
            for trial in trials
            if trial.feasible_probability + 1e-12 >= self.min_feasible_probability
        ]
        if not eligible:
            raise ValueError(
                "no candidate meets the minimum feasible probability; "
                "reduce stress range or feasibility threshold"
            )

        best = max(
            eligible,
            key=lambda item: (
                item.score,
                item.expected_profit,
                item.downside_profit,
                -item.bid_price,
            ),
        )
        return RiskOptimizationResult(
            target_unit_id=target_unit_id,
            risk_aversion=self.risk_aversion,
            tail_fraction=self.tail_fraction,
            best=best,
            trials=tuple(trials),
        )


def weighted_lower_tail_profit(
    outcomes: Iterable[ScenarioOutcome],
    tail_fraction: float,
) -> float:
    """Weighted mean profit in the worst ``tail_fraction`` of probability mass."""

    if not 0 < tail_fraction <= 1:
        raise ValueError("tail_fraction must be in (0, 1]")
    values = sorted(outcomes, key=lambda item: item.profit)
    if not values:
        raise ValueError("outcomes must not be empty")

    total_probability = sum(item.probability for item in values)
    if total_probability <= 0:
        raise ValueError("outcome probability must be positive")

    remaining = tail_fraction
    weighted_sum = 0.0
    for item in values:
        normalized_probability = item.probability / total_probability
        take = min(remaining, normalized_probability)
        weighted_sum += item.profit * take
        remaining -= take
        if remaining <= 1e-12:
            break
    return weighted_sum / tail_fraction


def build_stress_cases(
    base: MarketScenario,
    *,
    demand_multipliers: Iterable[float] = (0.9, 1.0, 1.1),
    competitor_bid_multipliers: Iterable[float] = (0.9, 1.0, 1.1),
) -> tuple[WeightedScenario, ...]:
    """Create transparent demand/competitor-price stress cases for teaching.

    These are synthetic sensitivity cases, not forecasts. The target unit's own
    bid is left untouched because the optimizer overwrites it for every trial.
    """

    demands = sorted({float(value) for value in demand_multipliers})
    competitor_prices = sorted({float(value) for value in competitor_bid_multipliers})
    if not demands or not competitor_prices:
        raise ValueError("stress multiplier sets must not be empty")
    if any(value <= 0 for value in demands + competitor_prices):
        raise ValueError("stress multipliers must be positive")

    cases: list[WeightedScenario] = []
    for demand_multiplier in demands:
        for bid_multiplier in competitor_prices:
            offers = tuple(
                offer
                if offer.unit_id == base.target_unit_id
                else offer.with_bid(round(offer.bid_price * bid_multiplier, 10))
                for offer in base.offers
            )
            scenario = replace(
                base,
                name=(
                    f"{base.name} | demand x{demand_multiplier:.2f} "
                    f"| competitors x{bid_multiplier:.2f}"
                ),
                demand_mw=round(base.demand_mw * demand_multiplier, 10),
                offers=offers,
                data_source="synthetic",
            )
            cases.append(
                WeightedScenario(
                    name=(
                        f"负荷×{demand_multiplier:.2f} / "
                        f"竞争报价×{bid_multiplier:.2f}"
                    ),
                    scenario=scenario,
                    probability=1.0,
                )
            )
    return tuple(cases)
