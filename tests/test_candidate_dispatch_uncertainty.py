"""New-bid dispatch envelopes: legal, ex ante, read-only and never PMSS profit."""
from __future__ import annotations

from dataclasses import replace

import pytest
from test_historical_validation import _fixture

from powerbid.candidate_dispatch_uncertainty import (
    assess_candidate_dispatch_uncertainty,
)
from powerbid.pmss_integration import BidSegment, snapshot_from_pmss
from powerbid.network_dispatch import network_from_dict


def _input():
    raw = _fixture()
    snap = snapshot_from_pmss(
        unit_tree=raw["unitTree"],
        unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    return snap, network_from_dict(raw["dcNetwork"])


def test_equal_price_candidate_has_visible_bounded_dispatch_uncertainty():
    snap, net = _input()
    # Both original synthetic bids have different prices; setting target G1
    # to G2's offer price creates tied-cost opportunities up to congested flow.
    g2_price = snap.bids["G2"][0].segments[0].price
    result = assess_candidate_dispatch_uncertainty(
        snap, net, "G1", [BidSegment(0, 100, g2_price)]
    )
    assert len(result.hours) == 24
    assert result.ambiguous_hours == 24
    assert all(item.range_width_mw > 0 for item in result.hours)
    assert result.maximum_accepted_mwh > result.minimum_accepted_mwh
    assert result.minimum_accepted_mwh <= result.default_lp_accepted_mwh <= result.maximum_accepted_mwh
    assert result.safe_for_live_submission is False
    assert result.counterfactual_pmss_verified is False
    assert result.uses_historical_outcomes_as_forecast is False


def test_distinct_bid_prices_make_target_allocation_effectively_fixed():
    snap, net = _input()
    result = assess_candidate_dispatch_uncertainty(
        snap, net, "G1", [BidSegment(0, 100, 10)]
    )
    assert result.ambiguous_hours == 0
    assert result.maximum_hourly_width_mw < 1.0
    assert result.hours[0].default_lp_accepted_mw == pytest.approx(
        result.hours[0].maximum_accepted_mw, abs=1e-3
    )


def test_candidate_must_obey_current_rule_not_old_saved_bid():
    snap, net = _input()
    with pytest.raises(ValueError, match="outside current PMSS"):
        assess_candidate_dispatch_uncertainty(
            snap, net, "G1", [BidSegment(0, 100, 1001)]
        )
    with pytest.raises(ValueError, match="capacity"):
        assess_candidate_dispatch_uncertainty(
            snap, net, "G1", [BidSegment(0, 110, 80)]
        )
    with pytest.raises(ValueError, match="Ambiguity threshold"):
        assess_candidate_dispatch_uncertainty(
            snap, net, "G1", [BidSegment(0, 100, 80)],
            ambiguity_threshold_mw=-1,
        )


def test_observed_pmss_history_has_no_place_in_candidate_range_inputs():
    snap, net = _input()
    new = (BidSegment(0, 100, 90),)
    actual = assess_candidate_dispatch_uncertainty(snap, net, "G1", new)
    # Bid/market snapshots carry no PMSS observed dispatch or observed LMP
    # input parameter, so those results cannot influence this calculation.
    repeat = assess_candidate_dispatch_uncertainty(snap, net, "G1", new)
    assert actual == repeat


def test_network_mapping_and_hourly_demand_are_validated_before_solving():
    snap, net = _input()
    changed = replace(
        net,
        hourly_demand_mw=net.hourly_demand_mw | {
            "B": (0.0,)+tuple(net.hourly_demand_mw["B"][1:])
        },
    )
    with pytest.raises(ValueError, match="Network nodal demand disagrees"):
        assess_candidate_dispatch_uncertainty(
            snap, changed, "G1", [BidSegment(0, 100, 80)]
        )
