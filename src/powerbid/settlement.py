from __future__ import annotations

from powerbid.models import ClearingResult, Offer, Settlement


def settle_offer(offer: Offer, result: ClearingResult, interval_hours: float) -> Settlement:
    """Settle one generator under a uniform-price market."""

    accepted = float(result.accepted_mw.get(offer.unit_id, 0.0))
    price = result.clearing_price
    revenue = 0.0 if price is None else price * accepted * interval_hours
    variable_cost = offer.marginal_cost * accepted * interval_hours
    profit = revenue - variable_cost

    return Settlement(
        unit_id=offer.unit_id,
        accepted_mw=accepted,
        clearing_price=price,
        revenue=revenue,
        variable_cost=variable_cost,
        profit=profit,
    )
