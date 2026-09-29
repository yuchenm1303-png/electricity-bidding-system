from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Offer:
    """A single generator supply offer for one market interval."""

    unit_id: str
    quantity_mw: float
    bid_price: float
    marginal_cost: float

    def __post_init__(self) -> None:
        if not self.unit_id:
            raise ValueError("unit_id must not be empty")
        if self.quantity_mw < 0:
            raise ValueError("quantity_mw must be non-negative")
        if self.bid_price < 0:
            raise ValueError("bid_price must be non-negative")
        if self.marginal_cost < 0:
            raise ValueError("marginal_cost must be non-negative")

    def with_bid(self, bid_price: float) -> Offer:
        return replace(self, bid_price=float(bid_price))


@dataclass(frozen=True, slots=True)
class MarketScenario:
    name: str
    demand_mw: float
    interval_hours: float
    target_unit_id: str
    offers: tuple[Offer, ...]
    description: str = ""
    data_source: str = "unknown"

    def __post_init__(self) -> None:
        if self.demand_mw < 0:
            raise ValueError("demand_mw must be non-negative")
        if self.interval_hours <= 0:
            raise ValueError("interval_hours must be positive")
        if not self.data_source:
            raise ValueError("data_source must not be empty")
        unit_ids = [offer.unit_id for offer in self.offers]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("unit_id values must be unique")
        if self.target_unit_id not in unit_ids:
            raise ValueError("target_unit_id must exist in offers")

    def replace_offer(self, unit_id: str, new_offer: Offer) -> MarketScenario:
        if new_offer.unit_id != unit_id:
            raise ValueError("replacement offer must keep the same unit_id")
        offers = tuple(new_offer if offer.unit_id == unit_id else offer for offer in self.offers)
        return replace(self, offers=offers)

    def get_offer(self, unit_id: str) -> Offer:
        for offer in self.offers:
            if offer.unit_id == unit_id:
                return offer
        raise KeyError(unit_id)


@dataclass(frozen=True, slots=True)
class ClearingResult:
    clearing_price: float | None
    accepted_mw: dict[str, float]
    demand_mw: float
    supplied_mw: float
    unserved_mw: float

    @property
    def feasible(self) -> bool:
        return self.unserved_mw <= 1e-9


@dataclass(frozen=True, slots=True)
class Settlement:
    unit_id: str
    accepted_mw: float
    clearing_price: float | None
    revenue: float
    variable_cost: float
    profit: float


@dataclass(frozen=True, slots=True)
class BidTrial:
    bid_price: float
    clearing_price: float | None
    accepted_mw: float
    revenue: float
    variable_cost: float
    profit: float
    feasible: bool


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    target_unit_id: str
    best: BidTrial
    trials: tuple[BidTrial, ...]
