"""13 UC fields: anonymous observations are NOT verified PMSS inputs."""
from copy import deepcopy

import pytest
from test_pmss_scene_constraint_evidence import fixture as scene_fixture
from test_pmss_technical_evidence import model as technical_fixture

from powerbid.pmss_scene_constraint_evidence import (
    summarize_scene_constraint_evidence,
)
from powerbid.pmss_technical_evidence import sanitize_pmss_technical_evidence
from powerbid.pmss_uc_evidence_gaps import (
    audit_pmss_uc_evidence_gaps,
)


def test_without_any_sources_every_uc_field_is_explicitly_blocked():
    snapshot, _ = technical_fixture()
    report = audit_pmss_uc_evidence_gaps(snapshot)
    assert report.unit_count == 2
    assert report.fields_required_per_unit == 13
    assert report.fields_with_any_anonymous_observations == 0
    assert report.fields_missing_observations == 13
    assert report.individually_verified_fields == 0
    assert report.independent_technical_parameters_ready is False
    assert report.scenario_switch_codes_interpreted is False
    assert report.generator_initial_states_confirmed is False
    assert all(field.status == "NO_FIELD_OBSERVATION" for field in report.fields)
    assert all(not field.usable_as_model_input for field in report.fields)


def test_two_readonly_sources_never_autofill_a_single_model_parameter():
    snapshot, private = technical_fixture()
    c, i = scene_fixture()
    technical = sanitize_pmss_technical_evidence(private, snapshot=snapshot)
    scene = summarize_scene_constraint_evidence(c, i, expected_units=2)
    report = audit_pmss_uc_evidence_gaps(
        snapshot, technical_evidence=technical, scene_constraint_evidence=scene,
    )
    f = {field.field: field for field in report.fields}
    assert report.fields_required_per_unit == 13
    assert report.fields_with_any_anonymous_observations == 10
    assert report.fields_missing_observations == 3
    assert report.individually_verified_fields == 0
    assert f["max_mw"].observed_source_field == "pdAdjustMax"
    assert f["max_mw"].aggregate_values_present == 2
    assert f["max_mw"].status == "ANONYMOUS_OBSERVATION_NOT_VERIFIED"
    assert f["ramp_up_mw"].observed_source_field == "incRate"
    assert f["ramp_up_mw"].relevant_switch_name_unverified == "ifConRamp"
    assert f["ramp_up_mw"].relevant_switch_value_1 == 1
    assert f["ramp_up_mw"].relevant_switch_value_0 == 1
    assert f["initial_on"].observed_source_field == "initialState"
    assert f["initial_on"].aggregate_values_present == 2
    assert f["initial_on"].semantically_verified is False
    assert f["initial_mw"].aggregate_values_present == 2
    assert f["initial_state_hours"].aggregate_values_present == 2
    assert f["startup_ramp_mw"].status == "NO_FIELD_OBSERVATION"
    assert f["shutdown_ramp_mw"].status == "NO_FIELD_OBSERVATION"
    assert f["shutdown_cost"].status == "NO_FIELD_OBSERVATION"
    assert all(not v.linked_to_individual_generator for v in report.fields)
    assert all(not v.usable_as_model_input for v in report.fields)
    assert "MUST_NEVER_LEAVE_TRUSTED_HOST" not in str(report)


def test_partial_coverage_not_falsely_reported_as_complete():
    snapshot, private = technical_fixture()
    private["units"]["datas"][1].pop("incRate")
    technical = sanitize_pmss_technical_evidence(private, snapshot=snapshot)
    report = audit_pmss_uc_evidence_gaps(snapshot, technical_evidence=technical)
    f = {field.field: field for field in report.fields}
    assert f["ramp_up_mw"].status == "PARTIAL_ANONYMOUS_OBSERVATION"
    assert f["ramp_up_mw"].aggregate_values_present == 1
    assert f["ramp_up_mw"].aggregate_rows_reported == 2
    assert f["ramp_down_mw"].status == "ANONYMOUS_OBSERVATION_NOT_VERIFIED"


def test_source_attestation_forgery_and_inconsistent_stats_fail_closed():
    snapshot, private = technical_fixture()
    technical = sanitize_pmss_technical_evidence(private, snapshot=snapshot)
    invalid = deepcopy(technical)
    invalid["jointMilpReady"] = True
    with pytest.raises(ValueError, match="cannot claim"):
        audit_pmss_uc_evidence_gaps(snapshot, technical_evidence=invalid)
    c, i = scene_fixture()
    scene = summarize_scene_constraint_evidence(c, i, expected_units=2)
    invalid = deepcopy(scene)
    invalid["initialFields"]["power"]["unitsVerified"] = True
    with pytest.raises(ValueError, match="not independently established"):
        audit_pmss_uc_evidence_gaps(
            snapshot, scene_constraint_evidence=invalid,
        )
    invalid = deepcopy(scene)
    invalid["switches"]["ifConRamp"]["value_1"] = 9
    with pytest.raises(ValueError, match="coverage"):
        audit_pmss_uc_evidence_gaps(
            snapshot, scene_constraint_evidence=invalid,
        )
