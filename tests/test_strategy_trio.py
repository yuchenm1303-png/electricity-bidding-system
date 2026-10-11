"""Safety regression tests for offline three-profile bidding recommendations."""
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from test_joint_market import _model

from powerbid.network_strategy import NetworkBidResult, NetworkDay, NetworkHour
from powerbid.pmss_integration import curve_for_period
from powerbid.strategy_trio import recommend_strategy_trio


def test_three_distinct_cost_covered_legal_offers_without_fabricated_physics():
    pytest.importorskip("scipy")
    snapshot, network, _ = _model()
    result = recommend_strategy_trio(snapshot, network, "G1")
    assert [c.profile for c in result.candidates] == ["收益优先", "均衡", "稳健"]
    assert len(set(c.periods for c in result.candidates)) == 3
    assert result.policies_screened >= 3
    assert set(result.missing_physical_unit_ids) == {"G1", "G2"}
    assert not result.real_pmss_clearing
    assert not result.safe_for_live_submission
    assert not result.physical_inputs_independently_verified
    for candidate in result.candidates:
        assert candidate.physical_status == "UNKNOWN_MISSING_TECHNICAL_INPUTS"
        assert candidate.integrated_net_profit is None
        assert candidate.local_candidate_usable is False
        assert all(block[2] >= snapshot.unit("G1").running_cost for block in candidate.price_blocks)
        assert 1 <= len(candidate.price_blocks) <= 5
        assert candidate.periods[0].start_period == 1
        assert candidate.periods[0].end_period == 24
        assert len(candidate.neutral_dc_dispatch_mw) == 24
        assert all(block[2] > 0 for block in candidate.price_blocks)
        assert curve_for_period(candidate.periods, 24) == curve_for_period(candidate.periods, 1)


def test_optional_complete_thermal_records_enable_local_joint_checks_only():
    pytest.importorskip("scipy")
    snapshot, network, spec = _model()
    result = recommend_strategy_trio(snapshot, network, "G1", technical=spec)
    assert result.missing_physical_unit_ids == ()
    assert any(c.physical_status == "LOCAL_DC_UC_FEASIBLE" for c in result.candidates)
    for candidate in result.candidates:
        if candidate.physical_status == "LOCAL_DC_UC_FEASIBLE":
            assert candidate.integrated_dispatch_mw is not None
            assert len(candidate.integrated_dispatch_mw) == 24
            assert candidate.startup_shutdown_cost is not None
        assert not result.safe_for_live_submission
    assert snapshot.bids["G1"][0].segments[0].price == 60


def test_price_ceiling_equal_to_running_cost_fails_closed():
    snapshot, network, _ = _model()
    snapshot = replace(
        snapshot, limits=replace(snapshot.limits, price_ceiling=50)
    )
    with pytest.raises(ValueError, match="price ceiling"):
        recommend_strategy_trio(snapshot, network, "G1")


def test_costless_input_cannot_emit_all_zero_bidding_curves():
    pytest.importorskip("scipy")
    snapshot, network, _ = _model()
    snapshot = replace(
        snapshot,
        units=tuple(
            replace(u, running_cost=0) if u.unit_id == "G1" else u
            for u in snapshot.units
        ),
    )
    result = recommend_strategy_trio(snapshot, network, "G1")
    assert all(
        any(block[2] > 0 for block in candidate.price_blocks)
        for candidate in result.candidates
    )


def test_24h_maxed_dispatch_never_gets_promoted_to_reliable_candidate():
    snapshot, network, spec = _model()

    def artificially_saturated(_snapshot, _network, _target, name, plan, scenarios, **_kw):
        hour = NetworkHour(1, 100.0, 60.0, 0.0, {}, {})
        days = tuple(
            NetworkDay(s.name, 1 / 3, 0.0, 2400.0, (hour,) * 24)
            for s in scenarios
        )
        return NetworkBidResult(name, tuple(plan), 0.0, 0.0, 0.0, 2400.0, 0.0, days)

    fake_hours = tuple(
        SimpleNamespace(accepted_by_unit={"G1": 100.0})
        for _ in range(24)
    )
    fake_joint = SimpleNamespace(
        expected_net_profit=0.0,
        scenarios=(SimpleNamespace(
            target_transition_cost=0.0,
            market=SimpleNamespace(hours=fake_hours),
        ),),
    )
    with (
        patch("powerbid.strategy_trio.evaluate_network_plan", side_effect=artificially_saturated),
        patch("powerbid.strategy_trio.evaluate_joint_bid", return_value=fake_joint),
    ):
        result = recommend_strategy_trio(snapshot, network, "G1", technical=spec)
    for candidate in result.candidates:
        assert candidate.full_capacity_dc_hours == 24
        assert candidate.physical_status == "LOCAL_DC_UC_FULL_OUTPUT_REVIEW"
        assert candidate.local_candidate_usable is False
        assert candidate.warnings
    assert asdict(result)["safe_for_live_submission"] is False


def test_invalid_partial_thermal_records_rejected_not_inferred():
    snapshot, network, spec = _model()
    with pytest.raises(ValueError, match="Every generator"):
        recommend_strategy_trio(snapshot, network, "G1", technical={"G1": spec["G1"]})
