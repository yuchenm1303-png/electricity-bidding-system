from __future__ import annotations

from collections.abc import Iterable

from powerbid.clearing.base import ClearingEngine
from powerbid.models import BidTrial, MarketScenario, OptimizationResult
from powerbid.settlement import settle_offer


class GridSearchBidOptimizer:
    """Evaluate candidate bid prices against a pluggable clearing engine."""

    def __init__(self, engine: ClearingEngine) -> None:
        self.engine = engine

    def optimize(
        self,
        scenario: MarketScenario,
        candidate_prices: Iterable[float],
    ) -> OptimizationResult:
        target = scenario.get_offer(scenario.target_unit_id)
        prices = sorted({float(price) for price in candidate_prices})
        if not prices:
            raise ValueError("candidate_prices must not be empty")
        if any(price < 0 for price in prices):
            raise ValueError("candidate prices must be non-negative")

        trials: list[BidTrial] = []
        for bid_price in prices:
            trial_offer = target.with_bid(bid_price)
            trial_scenario = scenario.replace_offer(target.unit_id, trial_offer)
            clearing = self.engine.clear(trial_scenario)
            settlement = settle_offer(trial_offer, clearing, scenario.interval_hours)
            trials.append(
                BidTrial(
                    bid_price=bid_price,
                    clearing_price=clearing.clearing_price,
                    accepted_mw=settlement.accepted_mw,
                    revenue=settlement.revenue,
                    variable_cost=settlement.variable_cost,
                    profit=settlement.profit,
                    feasible=clearing.feasible,
                )
            )

        feasible = [trial for trial in trials if trial.feasible]
        if not feasible:
            raise ValueError("no feasible candidate: market demand cannot be fully served")

        # Prefer more profit. For exact ties, prefer more accepted energy, then
        # the lower bid price as a conservative deterministic tie-breaker.
        best = max(feasible, key=lambda t: (t.profit, t.accepted_mw, -t.bid_price))
        return OptimizationResult(
            target_unit_id=target.unit_id,
            best=best,
            trials=tuple(trials),
        )


def price_grid(start: float, stop: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step must be positive")
    if stop < start:
        raise ValueError("stop must be >= start")

    values: list[float] = []
    current = float(start)
    while current <= stop + 1e-9:
        values.append(round(current, 10))
        current += step
    return values
