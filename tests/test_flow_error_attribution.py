"""Comparative counterfactual diagnostics never invent missing hours or claim causality."""
import pytest
from test_historical_validation import _fixture

from powerbid.flow_error_attribution import compare_dispatch_and_network_sources


def test_both_models_agree_for_exact_synthetic_fixture():
    report = compare_dispatch_and_network_sources(_fixture())
    c = report.comparison
    assert c.same_observation_set
    assert c.observed_line_points == 24
    assert c.original_model_line_points == 24
    assert c.independent_dispatch_flow_mae_mw == pytest.approx(0, abs=1e-7)
    assert c.observed_dispatch_flow_mae_mw == pytest.approx(0, abs=1e-7)
    assert c.absolute_mae_difference_mw == pytest.approx(0, abs=1e-7)
    assert c.remaining_error_ratio is None
    assert report.observed_dispatch.modeled_hours == 24
    assert "NOT a causal" in c.explanation


def test_fixed_observed_generator_output_separates_mismatched_bid_dispatch():
    raw = _fixture()
    # Put 15 MW more at G1 and 15 MW less at G2, preserving total demand.
    # The actual historical branch flow differs from independent bid clearing.
    raw["results"]["unitResults"][0]["accepted_mw"] = [45.0] * 24
    raw["results"]["unitResults"][1]["accepted_mw"] = [115.0] * 24
    raw["results"]["branchFlows"][0]["flow_mw"] = [45.0] * 24
    report = compare_dispatch_and_network_sources(raw)
    c = report.comparison
    assert c.same_observation_set
    assert c.independent_dispatch_flow_mae_mw == pytest.approx(15)
    assert c.observed_dispatch_flow_mae_mw == pytest.approx(0, abs=1e-7)
    assert c.absolute_mae_difference_mw == pytest.approx(15)
    assert c.remaining_error_ratio == pytest.approx(0)


def test_missing_injections_do_not_produce_misleading_coverage_matched_attribution():
    raw = _fixture()
    raw["results"]["unitResults"][0]["accepted_mw"][8] = None
    report = compare_dispatch_and_network_sources(raw)
    assert not report.comparison.same_observation_set
    assert report.comparison.absolute_mae_difference_mw is None
    assert report.comparison.remaining_error_ratio is None
    assert report.comparison.missing_dispatch_hours == 1


def test_unbalanced_historical_generation_disables_comparison():
    raw = _fixture()
    raw["results"]["unitResults"][0]["accepted_mw"][4] += 10
    report = compare_dispatch_and_network_sources(raw)
    assert not report.comparison.same_observation_set
    assert report.comparison.unbalanced_dispatch_hours == 1
    assert report.comparison.absolute_mae_difference_mw is None


def test_history_not_marked_historical_cannot_run_attribution():
    raw = _fixture()
    raw["historicalBacktestOnly"] = False
    with pytest.raises(ValueError, match="historical"):
        compare_dispatch_and_network_sources(raw)
