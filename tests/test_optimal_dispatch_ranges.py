"""Optimal-face intervals expose multiple equivalent dispatches honestly."""
import pytest

from powerbid.network_dispatch import DcLine, DcNetwork, DcOffer
from powerbid.optimal_dispatch_ranges import optimal_unit_dispatch_ranges


def _network():
    return DcNetwork(
        buses=("BUS",), lines=(), unit_bus={"G1": "BUS", "G2": "BUS"},
        hourly_demand_mw={"BUS": (100.0,) * 24}, slack_bus="BUS",
        base_mva=100, topology_source="synthetic example",
        demand_source="synthetic example",
    )


def test_equal_price_generator_offers_yield_wide_optimal_ranges():
    market = _network()
    offers = (DcOffer("G1", 1, 100, 50), DcOffer("G2", 1, 100, 50))
    result = optimal_unit_dispatch_ranges(market, offers, 1)
    assert result.minimum_offer_cost == pytest.approx(5000.0)
    assert not result.unique_dispatch_within_tolerance
    for generator in result.unit_ranges:
        assert generator.minimum_mw == pytest.approx(0.0, abs=1e-6)
        assert generator.maximum_mw == pytest.approx(100.0, abs=1e-6)
        assert generator.width_mw == pytest.approx(100.0, abs=1e-5)
    assert "independent" in result.label


def test_distinct_offer_prices_essentially_fix_dispatch():
    offers = (DcOffer("G1", 1, 100, 10), DcOffer("G2", 1, 100, 100))
    result = optimal_unit_dispatch_ranges(_network(), offers, 1)
    assert result.unique_dispatch_within_tolerance
    assert result.unit_ranges[0].minimum_mw == pytest.approx(100.0, abs=1e-4)
    assert result.unit_ranges[0].maximum_mw == pytest.approx(100.0, abs=1e-4)


def test_line_capacity_restricts_allocation_even_with_equal_price_offers():
    network = DcNetwork(
        buses=("A", "B"),
        lines=(DcLine("AB", "A", "B", 0.1, 30),),
        unit_bus={"G1": "A", "G2": "B"},
        hourly_demand_mw={"A": (0.0,) * 24, "B": (80.0,) * 24},
        slack_bus="A", base_mva=100,
        topology_source="synthetic", demand_source="synthetic",
    )
    offers = (DcOffer("G1", 1, 100, 50), DcOffer("G2", 1, 100, 50))
    result = optimal_unit_dispatch_ranges(network, offers, 1)
    assert result.unit_ranges[0].minimum_mw == pytest.approx(0)
    assert result.unit_ranges[0].maximum_mw == pytest.approx(30)
    assert result.unit_ranges[1].minimum_mw == pytest.approx(50)
    assert result.unit_ranges[1].maximum_mw == pytest.approx(80)


def test_forced_off_bound_collapses_that_generator_interval():
    offers = (DcOffer("G1", 1, 100, 50), DcOffer("G2", 1, 100, 50))
    result = optimal_unit_dispatch_ranges(
        _network(), offers, 1, forced_off_units=frozenset({"G1"})
    )
    assert result.unique_dispatch_within_tolerance
    assert result.unit_ranges[0].minimum_mw == pytest.approx(0)
    assert result.unit_ranges[0].maximum_mw == pytest.approx(0)
    assert result.unit_ranges[1].minimum_mw == pytest.approx(100)
    assert result.unit_ranges[1].maximum_mw == pytest.approx(100)


def test_invalid_tolerance_rejected_and_baseline_immutable():
    offers = (DcOffer("G1", 1, 100, 50), DcOffer("G2", 1, 100, 50))
    with pytest.raises(ValueError, match="tolerances"):
        optimal_unit_dispatch_ranges(_network(), offers, 1, cost_tolerance_abs=-1)
    with pytest.raises(ValueError, match="tolerances"):
        optimal_unit_dispatch_ranges(
            _network(), offers, 1, cost_tolerance_rel=float("nan")
        )
    assert offers[0].price == 50
