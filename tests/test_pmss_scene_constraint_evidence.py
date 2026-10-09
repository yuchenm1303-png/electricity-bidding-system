"""Evidence is source counts, never verified unit commitment parameters."""
from copy import deepcopy

import pytest

from powerbid.pmss_scene_constraint_evidence import (
    summarize_scene_constraint_evidence,
    validate_scene_constraint_evidence,
)


def fixture():
    c = {"rowCount": 2, "datas": [
        {"ifConRamp": 1, "ifConInitPower": 0, "ifConMinOnOffTm": True},
        {"ifConRamp": 0, "ifConInitPower": "1", "ifConMinOnOffTm": None},
    ]}
    i = {"rowCount": 2, "datas": [
        {"initialState": "on", "keepTime": 120, "power": 150},
        {"initialState": "off", "keepTime": 20, "power": 0},
    ]}
    return c, i


def test_collect_source_only_evidence_and_reject_verified_forgery():
    c, i = fixture()
    report = summarize_scene_constraint_evidence(c, i, expected_units=2)
    assert report["switches"]["ifConRamp"]["value_1"] == 1
    assert report["switches"]["ifConRamp"]["value_0"] == 1
    assert report["switches"]["ifConMinOnOffTm"]["missing"] == 1
    assert report["initialFields"]["keepTime"]["maximum"] == 120
    assert report["initialFields"]["initialState"]["numeric"] == 0
    parsed = validate_scene_constraint_evidence(report, expected_units=2)
    assert parsed["joint_milp_ready"] is False
    assert parsed["physical_units_verified"] is False
    evil = deepcopy(report)
    evil["jointMilpReady"] = True
    with pytest.raises(ValueError, match="cannot assert"):
        validate_scene_constraint_evidence(evil, expected_units=2)
    evil = deepcopy(report)
    evil["switches"]["ifConRamp"]["value_1"] = 2
    with pytest.raises(ValueError, match="coverage"):
        validate_scene_constraint_evidence(evil, expected_units=2)


def test_reject_incomplete_paging_and_sensitive_field_is_not_copied():
    c, i = fixture()
    c["datas"][0]["authorization"] = "NOT_ALLOWED_IN_EXPORTED_STATS"
    output = summarize_scene_constraint_evidence(c, i, expected_units=2)
    assert "authorization" not in str(output)
    c["rowCount"] = 3
    with pytest.raises(ValueError, match="pagination incomplete"):
        summarize_scene_constraint_evidence(c, i, expected_units=2)
    c["rowCount"] = 2
    i["datas"][0]["keepTime"] = float("nan")
    report = summarize_scene_constraint_evidence(c, i, expected_units=2)
    assert report["initialFields"]["keepTime"]["numeric"] == 1


def test_no_extra_key_or_modified_meaning_can_claim_readiness():
    c, i = fixture()
    evidence = summarize_scene_constraint_evidence(c, i, expected_units=2)
    evidence["other"] = "unknown"
    with pytest.raises(ValueError, match="structure"):
        validate_scene_constraint_evidence(evidence, expected_units=2)


def test_adapter_calls_only_two_confirmed_read_methods():
    from powerbid.adapters.teacher_platform import TeacherPlatformAdapter
    adapter = object.__new__(TeacherPlatformAdapter)
    calls = []
    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"rowCount": 0, "datas": []}
    adapter._request = fake_request
    adapter.get_scene_unit_constraints(scene_id="scene-1")
    adapter.get_unit_initial_state_inputs(
        scene_id="scene-1", project_id="project-1", case_id="case-1",
    )
    assert calls[0] == (
        "POST", "scene/unitParam/list",
        {"json_body": {"sceneId": "scene-1", "pageNo": 1, "pageSize": 999}},
    )
    assert calls[1] == (
        "GET", "project/getUnitInitialStateInput",
        {"params": {
            "sceneId": "scene-1", "projectId": "project-1",
            "caseId": "case-1", "pageNo": 1, "pageSize": 999,
        }},
    )
