"""Saved historical price conflicts are evidence, not permission for new offers."""
import pytest

from powerbid.pmss_bid_rule_safety import (
    audit_saved_bid_price_limits,
    validate_new_bid_prices,
    validate_new_curve,
)
from powerbid.pmss_integration import BidSegment, snapshot_from_pmss


def snapshot():
    return snapshot_from_pmss(
        unit_tree=[
            {"key": "G30", "title": "G30", "leaf": True,
             "pdAdjustMax": 100, "pdAdjustMin": 0,
             "runningCost": 20, "unitType": "coal"},
            {"key": "G31", "title": "G31", "leaf": True,
             "pdAdjustMax": 150, "pdAdjustMin": 0,
             "runningCost": 50, "unitType": "gas"},
        ],
        unit_bids={
            "G30": {"datas": [{
                "startPeriod": 1, "endPeriod": 24,
                "segmentDatas": [
                    {"startPower": 0, "endPower": 50, "price": 7000, "segmentOrder": 1},
                    {"startPower": 50, "endPower": 100, "price": 8000, "segmentOrder": 2},
                ],
            }]},
            "G31": {"datas": [{
                "startPeriod": 1, "endPeriod": 24,
                "segmentDatas": [{
                    "startPower": 0, "endPower": 150,
                    "price": 100, "segmentOrder": 1,
                }],
            }]},
        },
        market_system={"spotList": [{
            "marketAtomType": "DA", "unitPowerDeclareSegmentConstraint": 5,
            "priceLowerConstraint": 0, "priceUpperConstraint": 1000,
            "useSameBiddingCurve": 1,
        }]},
        demand_forecast_mw=[160]*24,
        forecast_source="Synthetic 24h input (not future forecast)",
    )


def test_historical_outliers_preserved_but_new_candidates_cannot_reuse_prices():
    snap = snapshot()
    audit = audit_saved_bid_price_limits(snap)
    assert audit.original_units_outside_current_range == 1
    assert audit.original_segments_outside_current_range == 2
    assert audit.largest_original_price == 8000
    assert audit.affected_unit_names == ("G30",)
    assert snap.bids["G30"][0].segments[0].price == 7000
    validate_new_bid_prices(snap, [0, 500, 1000])
    with pytest.raises(ValueError, match="market rule"):
        validate_new_bid_prices(snap, [1001])
    with pytest.raises(ValueError, match="market rule"):
        validate_new_curve(snap, "G30", [BidSegment(0, 100, 7000)])


def test_new_curve_enforces_capacity_and_finite_price():
    snap = snapshot()
    with pytest.raises(ValueError, match="capacity"):
        validate_new_curve(snap, "G30", [BidSegment(0, 110, 100)])
    with pytest.raises(ValueError, match="finite"):
        validate_new_bid_prices(snap, [float("nan")])
    with pytest.raises(ValueError, match="finite"):
        validate_new_bid_prices(snap, [float("inf")])


def test_pmss_mutating_posts_not_automatically_replayed_after_timeout():
    requests = pytest.importorskip("requests")
    from unittest.mock import Mock

    from powerbid.adapters.teacher_platform import (
        TeacherPlatformAdapter,
        TeacherPlatformError,
    )

    adapter = TeacherPlatformAdapter(base_url="https://example.invalid")
    adapter.session.request = Mock(side_effect=requests.exceptions.Timeout("synthetic"))
    with pytest.raises(TeacherPlatformError, match="after 1 attempt"):
        adapter.save_unit_bid({"dry": "test"}, commit=True)
    assert adapter.session.request.call_count == 1
    with pytest.raises(TeacherPlatformError, match="after 1 attempt"):
        adapter.run_clearing(case_id="fake", commit=True)
    assert adapter.session.request.call_count == 2

    with pytest.raises(TeacherPlatformError, match="after 3 attempt"):
        adapter.get_unit_results(case_id="fake", da_ids=["unit-1"])
    assert adapter.session.request.call_count == 5
    with pytest.raises(TeacherPlatformError, match="after 3 attempt"):
        adapter.get_unit_bid(scope_id="fake", unit_id="fake")
    assert adapter.session.request.call_count == 8
