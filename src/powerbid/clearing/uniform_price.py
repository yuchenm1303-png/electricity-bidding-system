from __future__ import annotations

from collections import defaultdict
from itertools import groupby

from powerbid.models import ClearingResult, MarketScenario


class UniformPriceClearingEngine:
    """Simple single-zone uniform-price market clearing.

    Supply offers are sorted from low to high price. If several offers share
    the marginal price, the remaining demand is allocated pro-rata across that
    price group. All accepted generation is settled at the marginal clearing
    price.
    """

    def clear(self, scenario: MarketScenario) -> ClearingResult:
        accepted: dict[str, float] = defaultdict(float)
        demand = float(scenario.demand_mw)

        if demand <= 1e-12:
            return ClearingResult(
                clearing_price=0.0,
                accepted_mw={offer.unit_id: 0.0 for offer in scenario.offers},
                demand_mw=demand,
                supplied_mw=0.0,
                unserved_mw=0.0,
            )

        offers = sorted(scenario.offers, key=lambda offer: (offer.bid_price, offer.unit_id))
        remaining = demand
        clearing_price: float | None = None

        for price, grouped in groupby(offers, key=lambda offer: offer.bid_price):
            group = list(grouped)
            group_capacity = sum(offer.quantity_mw for offer in group)
            if group_capacity <= 1e-12:
                continue

            if remaining > group_capacity + 1e-12:
                for offer in group:
                    accepted[offer.unit_id] += offer.quantity_mw
                remaining -= group_capacity
                clearing_price = float(price)
                continue

            ratio = max(0.0, min(1.0, remaining / group_capacity))
            for offer in group:
                accepted[offer.unit_id] += offer.quantity_mw * ratio
            clearing_price = float(price)
            remaining = 0.0
            break

        result_map = {offer.unit_id: float(accepted[offer.unit_id]) for offer in scenario.offers}
        supplied = sum(result_map.values())
        unserved = max(0.0, demand - supplied)

        return ClearingResult(
            clearing_price=clearing_price,
            accepted_mw=result_map,
            demand_mw=demand,
            supplied_mw=supplied,
            unserved_mw=unserved,
        )
