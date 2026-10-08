import pytest

from powerbid.pmss_integration import (
    BidSegment,
    MarketLimits,
    curve_for_period,
    flatten_pmss_units,
    parse_period_bids,
    parse_unit_clearing,
    read_24_values,
    selected_leaf_ids,
    snapshot_from_pmss,
)
from powerbid.pmss_strategy import (
    build_pmss_dry_run_payload,
    evaluate_curve,
    optimize_segmented_bid,
    validate_curve,
)


def _tree():
    return [
        {
            "key": "group", "title": "发电机组", "leaf": False,
            "children": [
                {
                    "key": "G30", "title": "G30 燃煤", "leaf": True,
                    "pdAdjustMax": 100, "pdAdjustMin": 15,
                    "mvarate": 110, "runningCost": 50, "unitType": "coal",
                },
                {
                    "key": "G31", "title": "G31 燃气", "leaf": True,
                    "pdAdjustMax": 200, "pdAdjustMin": 0,
                    "mvarate": 210, "runningCost": 80, "unitType": "gas",
                },
            ],
        }
    ]


def _bid(price, capacity):
    return {
        "datas": [{
            "startPeriod": 1,
            "endPeriod": 24,
            "segmentDatas": [
                {"startPower": 0, "endPower": capacity, "price": price, "segmentOrder": 1}
            ],
        }]
    }


def _snapshot():
    return snapshot_from_pmss(
        unit_tree=_tree(),
        unit_bids={"G30": _bid(60, 100), "G31": _bid(80, 200)},
        market_system={"spotList": [{
            "marketAtomType": "DA",
            "unitPowerDeclareSegmentConstraint": 5,
            "priceLowerConstraint": 0,
            "priceUpperConstraint": 1000,
            "useSameBiddingCurve": 1,
        }]},
        demand_forecast_mw=[180] * 24,
        forecast_source="user-provided forecast (test)",
    )


def test_unit_mapping_preserves_adjustable_capacity_cost_and_type():
    units = flatten_pmss_units(_tree())
    assert [u.unit_id for u in units] == ["G30", "G31"]
    assert units[0].capacity_mw == 100
    assert units[0].running_cost == 50
    assert units[0].min_power_mw == 15


def test_period_bids_keep_all_segment_breaks_and_prices():
    parsed = parse_period_bids({
        "datas": [
            {"startPeriod": 1, "endPeriod": 12, "segmentDatas": [
                {"segmentOrder": 2, "startPower": 50, "endPower": 100, "price": 80},
                {"segmentOrder": 1, "startPower": 0, "endPower": 50, "price": 60},
            ]},
            {"startPeriod": 13, "endPeriod": 24, "segmentDatas": [
                {"segmentOrder": 1, "startPower": 0, "endPower": 100, "price": 70},
            ]},
        ],
    })
    assert [x.price for x in curve_for_period(parsed, 2)] == [60, 80]
    assert [x.price for x in curve_for_period(parsed, 20)] == [70]
    with pytest.raises(ValueError, match="Period 12"):
        curve_for_period((parsed[0], parsed[0]), 12)


def test_24_hour_forecast_required_and_not_inferred_from_results():
    with pytest.raises(ValueError, match="24 periods"):
        snapshot_from_pmss(
            unit_tree=_tree(),
            unit_bids={"G30": _bid(60, 100), "G31": _bid(80, 200)},
            market_system={"spotList": [{
                "marketAtomType": "DA",
                "unitPowerDeclareSegmentConstraint": 5,
                "useSameBiddingCurve": 1,
            }]},
            demand_forecast_mw=[180],
            forecast_source="test",
        )


def test_market_price_caps_are_metadata_not_hard_validation():
    snap = _snapshot()
    assert snap.limits.price_ceiling == 1000
    external = parse_period_bids(_bid(7000, 100))
    assert external[0].segments[0].price == 7000


def test_confirmed_unit_result_parses_24_hour_power_price_income():
    row = {
        "elementId": "G30", "elementName": "G30", "marketTypeAtom": "DA",
        "power": {"datas": [{"value": i} for i in range(24)], "sum": 276},
        "price": {"datas": [500] * 24, "sum": None},
        "income": {"datas": [1000] * 24, "sum": 24000},
    }
    parsed = parse_unit_clearing({"periodNum": 24, "datas": [row]})
    assert parsed[0].accepted_mw[23] == 23
    assert parsed[0].clearing_prices[0] == 500
    assert parsed[0].income[0] == 1000
    with pytest.raises(ValueError, match="expected 24"):
        read_24_values({"datas": [1]}, "power")


def test_result_selection_is_market_specific():
    tree = [
        {"key": "DA", "title": "日前", "children": [
            {"key": "G30_DA", "leaf": True},
            {"key": "G31_DA", "leaf": True},
        ]},
        {"key": "RT", "title": "实时", "children": [
            {"key": "G30_RT", "leaf": True},
        ]},
    ]
    assert selected_leaf_ids(tree, "DA") == ["G30_DA", "G31_DA"]
    assert selected_leaf_ids(tree, "RT") == ["G30_RT"]
    with pytest.raises(ValueError):
        selected_leaf_ids(tree, "BAD")


def test_five_segment_price_quantity_optimizer_does_not_degrade_seed():
    snap = _snapshot()
    result = optimize_segmented_bid(
        snap,
        "G30",
        candidate_prices=[50, 60, 70, 80, 90],
        quantity_step_mw=5,
        iterations=6,
    )
    assert len(result.recommended.segments) == 5
    assert result.recommended.total_profit >= 0
    assert result.recommended.segments[-1].end_power == 100
    assert len(result.recommended.hours) == 24
    assert all(h.feasible for h in result.recommended.hours)
    assert result.evaluated_curves > 2
    validate_curve(result.recommended.segments)
    # The imported one-block curve is valid for comparative baseline simulation.
    assert result.baseline.total_profit == evaluate_curve(
        snap, "G30", (BidSegment(0, 100, 60),)
    ).total_profit


def test_infeasible_supply_is_never_presented_as_recommendation():
    snap = _snapshot()
    # The real plant total available capacity is 300 MW; 400 MW is infeasible.
    from dataclasses import replace
    larger_load = replace(snap, demand_forecast_mw=(400.0,) * 24)
    with pytest.raises(ValueError, match="exceed available offers"):
        optimize_segmented_bid(larger_load, "G30", [50, 70, 90])


def test_preview_payload_does_not_do_network_io():
    payload = build_pmss_dry_run_payload(
        scope_id="placeholder", unit_id="G30",
        segments=[BidSegment(0, 20, 50), BidSegment(20, 100, 70)],
    )
    assert payload["datas"][0]["segmentDatas"][1]["segmentOrder"] == 2
    assert payload["unitId"] == "G30"
    with pytest.raises(ValueError):
        validate_curve([BidSegment(0, 30, 20), BidSegment(40, 100, 25)])
