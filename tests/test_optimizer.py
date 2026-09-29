from powerbid.clearing.uniform_price import UniformPriceClearingEngine
from powerbid.models import MarketScenario, Offer
from powerbid.optimizer import GridSearchBidOptimizer, price_grid


def test_grid_search_finds_best_bid_in_teaching_scenario() -> None:
    scenario = MarketScenario(
        name="optimizer-test",
        demand_mw=700,
        interval_hours=1.0,
        target_unit_id="G1",
        offers=(
            Offer("G1", 300, 220, 180),
            Offer("G2", 300, 190, 185),
            Offer("G3", 200, 250, 235),
            Offer("G4", 500, 400, 365),
        ),
    )

    result = GridSearchBidOptimizer(UniformPriceClearingEngine()).optimize(
        scenario, price_grid(180, 400, 10)
    )

    assert result.best.bid_price == 390
    assert result.best.clearing_price == 390
    assert result.best.accepted_mw == 200
    assert result.best.profit == 42000


def test_price_grid_includes_stop_when_aligned() -> None:
    assert price_grid(10, 30, 10) == [10.0, 20.0, 30.0]
