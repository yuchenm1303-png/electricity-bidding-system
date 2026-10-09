"""Historical optimal-face analysis never treats fitted original bids as new-bid evidence."""
from test_historical_validation import _fixture

import pytest

from powerbid.historical_ambiguity import audit_historical_optimal_ambiguity


def test_perfect_history_can_lie_on_a_nonunique_optimal_face():
    result = audit_historical_optimal_ambiguity(_fixture())
    assert result.case_date == "2025-09-01"
    assert result.examined_hours == 24
    assert result.observed_complete_hours == 24
    assert result.observed_joint_network_feasible_hours == 24
    assert result.observed_joint_model_optimal_hours == 24
    assert result.observed_individual_in_range == 48
    assert "NOT proof" in result.disclaimer


def test_missing_actual_unit_hour_is_not_filled_or_jointly_certified():
    raw = _fixture()
    raw["results"]["unitResults"][0]["accepted_mw"][3] = None
    result = audit_historical_optimal_ambiguity(raw)
    assert result.observed_complete_hours == 23
    assert result.observed_joint_model_optimal_hours == 23
    assert result.hours[3].observed_jointly_feasible is None
    assert result.observed_individual_evaluated == 47


def test_historical_dispatch_requires_exact_ids_and_provenance():
    raw = _fixture()
    raw["historicalBacktestOnly"] = False
    with pytest.raises(ValueError, match="historical"):
        audit_historical_optimal_ambiguity(raw)
    raw = _fixture()
    raw["results"]["unitResults"][0]["unit_id"] = "wrong"
    with pytest.raises(ValueError, match="IDs disagree"):
        audit_historical_optimal_ambiguity(raw)


def test_an_observed_original_dispatch_can_be_infeasible_for_dc_constraints():
    raw = _fixture()
    raw["results"]["unitResults"][0]["accepted_mw"] = [200.0] * 24
    raw["results"]["unitResults"][1]["accepted_mw"] = [0.0] * 24
    result = audit_historical_optimal_ambiguity(raw)
    assert result.observed_joint_network_feasible_hours == 0
    assert result.observed_joint_model_optimal_hours == 0
