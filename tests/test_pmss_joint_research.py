"""Reject fictional PMSS thermal inputs; exercise the integrated MILP on fixtures."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from powerbid.network_dispatch import network_from_dict
from powerbid.pmss_integration import snapshot_from_pmss
from powerbid.pmss_joint_research import (
    assess_joint_readiness, compare_joint_legal_candidates,
)
from powerbid.strategy_lab import BidPolicy

EXAMPLES = Path(__file__).resolve().parents[1] / "data" / "examples"


def fixtures():
    def load(name):
        return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    raw = load("synthetic_dc_pmss.json")
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    return snapshot, network_from_dict(load("synthetic_dc_network.json")), load(
        "synthetic_joint_technical.json"
    )


def test_refuse_missing_machine_and_unknown_ids_and_no_source():
    snapshot, _, specs = fixtures()
    without = deepcopy(specs)
    without.pop("G2")
    state = assess_joint_readiness(snapshot, without, source="synthetic")
    assert state.ready is False
    assert state.missing_unit_ids == ("G2",)
    assert state.independently_verified is False
    assert assess_joint_readiness(snapshot, None).supplied_units == 0
    assert assess_joint_readiness(snapshot, specs).ready is False
    without = deepcopy(specs)
    without["not-a-real-unit"] = deepcopy(without["G1"])
    assert assess_joint_readiness(
        snapshot, without, source="synthetic"
    ).unexpected_unit_ids == ("not-a-real-unit",)


def test_refuse_guessed_boolean_numeric_string_unknown_or_incomplete_fields():
    snapshot, _, specs = fixtures()
    cases = (
        ("initial_on", 1),
        ("startup_cost", float("inf")),
        ("ramp_up_mw", "30"),
        ("initial_state_hours", 0),
        ("max_mw", 9999),
        ("unit_id", "OTHER"),
    )
    for field, value in cases:
        manipulated = deepcopy(specs)
        manipulated["G1"][field] = value
        state = assess_joint_readiness(snapshot, manipulated, source="synthetic")
        assert not state.ready
        assert "G1" in state.invalid
    missing = deepcopy(specs)
    missing["G1"].pop("min_down_hours")
    assert not assess_joint_readiness(snapshot, missing, source="synthetic").ready


def test_integrated_24h_two_legal_candidates_return_research_only():
    pytest.importorskip("scipy")
    snapshot, network, specs = fixtures()
    state = assess_joint_readiness(snapshot, specs, source="synthetic")
    assert state.ready is True
    assert state.independently_verified is False
    result = compare_joint_legal_candidates(
        snapshot, network, specs, "G1",
        technical_source="synthetic",
        technical_source_description="Bundled artificial two-unit dataset",
        policies=(BidPolicy("cost"), BidPolicy("markup20", markup=20)),
    )
    assert result.safe_for_live_submission is False
    assert result.pmss_write_performed is False
    assert result.pmss_clearing_executed is False
    assert result.validated_against_pmss is False
    assert result.top_candidate in result.ranked
    assert len(result.ranked) == 2
    assert all(len(x.dispatch_24h) == 24 for x in result.ranked)
    assert all(len(x.segments) == 5 for x in result.ranked)
    assert all(max(s[2] for s in x.segments) <= snapshot.limits.price_ceiling
               for x in result.ranked)


def test_joint_strategy_never_runs_if_technical_source_or_units_missing():
    snapshot, network, specs = fixtures()
    for manipulated, source in (
        ({}, "synthetic"),
        (specs, ""),
        (specs, "unsupported_source"),
    ):
        with pytest.raises(ValueError, match="blocked"):
            compare_joint_legal_candidates(
                snapshot, network, manipulated, "G1",
                technical_source=source,
                technical_source_description="some dataset",
            )


def test_joint_strategies_require_typed_provenance_and_resource_bounds():
    snapshot, network, specs = fixtures()
    with pytest.raises(ValueError, match="source description"):
        compare_joint_legal_candidates(
            snapshot, network, specs, "G1",
            technical_source="synthetic",
            technical_source_description=" ",
        )
    with pytest.raises(ValueError, match="1..3"):
        compare_joint_legal_candidates(
            snapshot, network, specs, "G1",
            technical_source="synthetic",
            technical_source_description="synthetic",
            policies=(),
        )
    with pytest.raises(ValueError, match="timeout"):
        compare_joint_legal_candidates(
            snapshot, network, specs, "G1",
            technical_source="synthetic",
            technical_source_description="synthetic",
            solver_timeout_seconds=50,
        )
