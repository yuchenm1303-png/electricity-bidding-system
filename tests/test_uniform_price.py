from powerbid.clearing.uniform_price import UniformPriceClearingEngine
from powerbid.models import MarketScenario, Offer


def scenario(offers: tuple[Offer, ...], demand: float) -> MarketScenario:
    return MarketScenario(
        name="test",
        demand_mw=demand,
        interval_hours=1.0,
        target_unit_id=offers[0].unit_id,
        offers=offers,
    )


def test_uniform_price_dispatches_merit_order() -> None:
    offers = (
        Offer("A", 100, 20, 15),
        Offer("B", 100, 40, 30),
        Offer("C", 100, 60, 50),
    )
    result = UniformPriceClearingEngine().clear(scenario(offers, 150))

    assert result.feasible
    assert result.clearing_price == 40
    assert result.accepted_mw == {"A": 100.0, "B": 50.0, "C": 0.0}


def test_equal_price_marginal_offers_are_prorated() -> None:
    offers = (
        Offer("A", 100, 20, 15),
        Offer("B", 100, 40, 30),
        Offer("C", 300, 40, 35),
    )
    result = UniformPriceClearingEngine().clear(scenario(offers, 200))

    assert result.clearing_price == 40
    assert result.accepted_mw["A"] == 100
    assert result.accepted_mw["B"] == 25
    assert result.accepted_mw["C"] == 75


def test_shortage_is_reported() -> None:
    offers = (Offer("A", 100, 20, 15), Offer("B", 50, 40, 30))
    result = UniformPriceClearingEngine().clear(scenario(offers, 200))

    assert not result.feasible
    assert result.supplied_mw == 150
    assert result.unserved_mw == 50
