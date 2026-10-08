from __future__ import annotations

import pytest

from powerbid.pmss_dc_network import (
    evaluate_dc_bid,
    parse_grid,
    solve_dc_hour,
)
from powerbid.pmss_integration import BidSegment, snapshot_from_pmss


def sample_market():
    return snapshot_from_pmss(
        unit_tree=[
            {"key": "G1", "title": "G1", "leaf": True,
             "pdAdjustMax": 120, "pdAdjustMin": 0,
             "runningCost": 5, "unitType": "coal"},
            {"key": "G2", "title": "G2", "leaf": True,
             "pdAdjustMax": 120, "pdAdjustMin": 0,
             "runningCost": 20, "unitType": "gas"},
        ],
        unit_bids={
            "G1": {"datas": [{"startPeriod": 1, "endPeriod": 24, "segmentDatas": [
                {"startPower": 0, "endPower": 120, "price": 10, "segmentOrder": 1},
            ]}]},
            "G2": {"datas": [{"startPeriod": 1, "endPeriod": 24, "segmentDatas": [
                {"startPower": 0, "endPower": 120, "price": 50, "segmentOrder": 1},
            ]}]},
        },
        market_system={"spotList": [{
            "marketAtomType": "DA", "unitPowerDeclareSegmentConstraint": 5,
            "priceLowerConstraint": 0, "priceUpperConstraint": 1000,
            "useSameBiddingCurve": 1,
        }]},
        demand_forecast_mw=[100] * 24,
        forecast_source="Synthetic network test, no PMSS transaction",
    )


def _grid_payload(line_limit=50):
    return {
        "schema": "powerbid.pmss.dc-grid.v1",
        "provenance": "synthetic 2-bus deterministic verification",
        "buses": [{"bus": "A", "loadMw": [0] * 24},
                  {"bus": "B", "loadMw": [100] * 24}],
        "lines": [{
            "lineId": "L1", "fromBus": "A", "toBus": "B",
            "x": 0.1, "limitMw": line_limit,
        }],
        "unitBuses": {"G1": "A", "G2": "B"},
    }


def test_network_parser_rejects_missing_unit_location():
    example = _grid_payload()
    example["unitBuses"].pop("G2")
    with pytest.raises(ValueError, match="unit-to-bus"):
        parse_grid(example, snapshot=sample_market())


def test_network_parser_rejects_mismatched_nodal_load_and_disconnected_bus():
    grid = _grid_payload()
    grid["buses"][1]["loadMw"][2] = 99
    with pytest.raises(ValueError, match="mismatches"):
        parse_grid(grid, snapshot=sample_market())
    grid = _grid_payload()
    grid["buses"].append({"bus": "C", "loadMw": [0] * 24})
    with pytest.raises(ValueError, match="Disconnected"):
        parse_grid(grid, snapshot=sample_market())


def test_network_parser_rejects_unsafe_line_guesses():
    grid = _grid_payload()
    grid["lines"][0].pop("limitMw")
    with pytest.raises(ValueError, match="line needs|line needs|Each line"):
        parse_grid(grid)
    grid = _grid_payload()
    grid["lines"][0]["x"] = 0
    with pytest.raises(ValueError, match="positive"):
        parse_grid(grid)


def test_two_bus_dc_dispatch_congestion_and_local_lmps():
    pytest.importorskip("scipy")
    snapshot = sample_market()
    grid = parse_grid(_grid_payload(), snapshot=snapshot)
    row = solve_dc_hour(grid, snapshot, 1, target_unit_id="G1")
    assert row.accepted_mw["G1"] == pytest.approx(50, abs=1e-6)
    assert row.accepted_mw["G2"] == pytest.approx(50, abs=1e-6)
    assert row.flows_mw["L1"] == pytest.approx(50, abs=1e-6)
    assert row.lmp_by_bus["A"] == pytest.approx(10, abs=1e-5)
    assert row.lmp_by_bus["B"] == pytest.approx(50, abs=1e-5)
    assert row.congested_lines == ("L1",)
    assert row.target_profit == pytest.approx(250.0, abs=1e-5)
    report = evaluate_dc_bid(grid, snapshot, "G1")
    assert len(report.hours) == 24
    assert report.hours_with_binding_lines == 24
    assert report.max_line_utilization == pytest.approx(1.0)
    assert report.total_accepted_mwh == pytest.approx(1200.0)


def test_network_counterfactual_changes_nodal_price_without_platform_call():
    pytest.importorskip("scipy")
    snapshot = sample_market()
    grid = parse_grid(_grid_payload(120), snapshot=snapshot)
    baseline = solve_dc_hour(grid, snapshot, 1, target_unit_id="G1")
    assert baseline.accepted_mw["G1"] == pytest.approx(100)
    assert baseline.lmp_by_bus["B"] == pytest.approx(10)
    changed = solve_dc_hour(
        grid, snapshot, 1, target_unit_id="G1",
        target_segments=(BidSegment(0.0, 120.0, 90.0),),
    )
    assert changed.accepted_mw["G1"] == pytest.approx(0)
    assert changed.accepted_mw["G2"] == pytest.approx(100)
    assert changed.lmp_by_bus["B"] == pytest.approx(50)


def test_infeasible_network_is_not_reported_as_profitable():
    pytest.importorskip("scipy")
    snapshot = sample_market()
    grid = parse_grid(_grid_payload(50), snapshot=snapshot)
    with pytest.raises(ValueError, match="infeasible"):
        solve_dc_hour(
            grid, snapshot, 1, target_unit_id="G1",
            target_segments=(BidSegment(0.0, 10.0, 0.0),),
        )
