from powerbid.clearing.uniform_price import UniformPriceClearingEngine
from powerbid.models import MarketScenario, Offer
from powerbid.risk import RiskAwareBidOptimizer, WeightedScenario, build_stress_cases


def _scenario(name: str, demand_mw: float) -> MarketScenario:
    return MarketScenario(
        name=name,
        demand_mw=demand_mw,
        interval_hours=1.0,
        target_unit_id="G1",
        offers=(
            Offer("G1", quantity_mw=100.0, bid_price=55.0, marginal_cost=50.0),
            Offer("G2", quantity_mw=100.0, bid_price=60.0, marginal_cost=55.0),
        ),
        data_source="synthetic",
    )


def test_risk_aversion_can_change_the_recommended_bid() -> None:
    cases = (
        WeightedScenario("low demand", _scenario("low", 100.0), 0.5),
        WeightedScenario("high demand", _scenario("high", 150.0), 0.5),
    )
    engine = UniformPriceClearingEngine()

    neutral = RiskAwareBidOptimizer(
        engine, risk_aversion=0.0, tail_fraction=0.5
    ).optimize(cases, [55.0, 90.0])
    cautious = RiskAwareBidOptimizer(
        engine, risk_aversion=1.0, tail_fraction=0.5
    ).optimize(cases, [55.0, 90.0])

    assert neutral.best.bid_price == 90.0
    assert neutral.best.expected_profit == 1000.0
    assert cautious.best.bid_price == 55.0
    assert cautious.best.downside_profit == 500.0


def test_build_stress_cases_changes_only_competitors_and_demand() -> None:
    base = _scenario("base", 100.0)
    cases = build_stress_cases(
        base,
        demand_multipliers=(0.9, 1.1),
        competitor_bid_multipliers=(0.8, 1.2),
    )

    assert len(cases) == 4
    for case in cases:
        scenario = case.scenario
        assert scenario.get_offer("G1").bid_price == 55.0
        assert scenario.demand_mw in {90.0, 110.0}
        assert scenario.get_offer("G2").bid_price in {48.0, 72.0}
        assert scenario.data_source == "synthetic"
