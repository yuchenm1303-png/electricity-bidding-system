"""Tests for PMSS original-bid ex-post zero-generation restrictions."""
from test_historical_validation import _fixture

import pytest

from powerbid.expost_commitment_diagnostics import replay_zero_output_restriction
from powerbid.network_dispatch import DcInfeasibleError, DcOffer, dc_clear_hour
from test_network_strategy import _network


def test_optional_forced_off_dc_clearing_changes_dispatch_without_changing_offers():
    network = _network(loads=80, thermal_limit=40)
    offers = (
        DcOffer("G1", 1, 100.0, 10.0),
        DcOffer("G2", 1, 150.0, 90.0),
    )
    ordinary = dc_clear_hour(network, offers, 1)
    restricted = dc_clear_hour(
        network, offers, 1, forced_off_units=frozenset({"G1"})
    )
    assert ordinary.accepted_by_unit["G1"] == pytest.approx(40.0)
    assert restricted.accepted_by_unit["G1"] == pytest.approx(0.0)
    assert restricted.accepted_by_unit["G2"] == pytest.approx(80.0)
    assert offers[0].quantity_mw == 100.0
    with pytest.raises(ValueError, match="mapped network"):
        dc_clear_hour(network, offers, 1, forced_off_units=frozenset({"UNKNOWN"}))
    with pytest.raises(DcInfeasibleError):
        dc_clear_hour(
            _network(loads=160, thermal_limit=40), offers, 1,
            forced_off_units=frozenset({"G1"}),
        )


def test_perfect_synthetic_original_case_has_no_observed_zero_hours():
    report = replay_zero_output_restriction(_fixture())
    assert report.case_date == "2025-09-01"
    assert report.paired_hours == 24
    assert report.observed_zero_unit_hours == 0
    assert report.masked_infeasible_hours == 0
    assert report.baseline_paired_dispatch_mae_mw == pytest.approx(0)
    assert report.masked_paired_dispatch_mae_mw == pytest.approx(0)
    assert "EX-POST" in report.disclaimer


def test_observed_zero_known_expost_can_improve_matched_dispatch():
    case = _fixture()
    case["demandForecastMw"] = [80.0] * 24
    case["dcNetwork"]["hourlyDemandMw"]["B"] = [80.0] * 24
    case["results"]["unitResults"][0]["accepted_mw"] = [0.0] * 24
    case["results"]["unitResults"][1]["accepted_mw"] = [80.0] * 24
    case["results"]["branchFlows"][0]["flow_mw"] = [0.0] * 24
    report = replay_zero_output_restriction(case)
    assert report.paired_hours == 24
    assert report.observed_zero_unit_hours == 24
    assert report.baseline_positive_on_observed_zero_unit_hours == 24
    assert report.baseline_paired_dispatch_mae_mw > 0
    assert report.masked_paired_dispatch_mae_mw == pytest.approx(0)
    assert report.masked_paired_line_abs_mae_mw == pytest.approx(0)


def test_if_forced_off_causes_infeasibility_exclude_from_comparable_mae():
    case = _fixture()
    case["results"]["unitResults"][0]["accepted_mw"] = [0.0] * 24
    case["results"]["unitResults"][1]["accepted_mw"] = [160.0] * 24
    report = replay_zero_output_restriction(case)
    assert report.paired_hours == 0
    assert report.masked_infeasible_hours == 24
    assert report.baseline_paired_dispatch_mae_mw is None
    assert report.masked_paired_dispatch_mae_mw is None
    assert all(item.status == "MASKED_DISPATCH_INFEASIBLE" for item in report.hours)


def test_missing_actual_dispatch_not_silently_filled_as_zero():
    case = _fixture()
    case["results"]["unitResults"][0]["accepted_mw"][3] = None
    report = replay_zero_output_restriction(case)
    assert report.paired_hours == 23
    assert report.missing_observation_hours == 1
    assert report.hours[3].status == "MISSING_HISTORICAL_DISPATCH"
    assert report.units[0].compared_hours == 23


def test_history_provenance_and_market_identity_fail_closed():
    case = _fixture()
    case["historicalBacktestOnly"] = False
    with pytest.raises(ValueError, match="historical"):
        replay_zero_output_restriction(case)
    case = _fixture()
    case["results"]["unitResults"][0]["unit_id"] = "wrong"
    with pytest.raises(ValueError, match="IDs"):
        replay_zero_output_restriction(case)
    case = _fixture()
    with pytest.raises(ValueError, match="between"):
        replay_zero_output_restriction(case, zero_tolerance_mw=2.0)
