"""Online PMSS scene evidence must use exactly the selected read-only case."""
from __future__ import annotations

import json
import os
from copy import deepcopy

import pytest
from test_pmss_scene_constraint_evidence import fixture as scene_fixture
from test_pmss_web_api import _synthetic_network_case

from powerbid.adapters.teacher_platform import (
    TeacherPlatformAuthenticationExpired,
    TeacherPlatformContext,
)
from powerbid.pmss_evidence_attachment import verify_pmss_evidence_binding
from powerbid.pmss_scene_evidence_export import collect_same_case_scene_evidence


class ReadOnlyFake:
    def __init__(self):
        self.events = []
        self.calc, self.initial = scene_fixture()
        self.cases = ({
            "caseDate": "2025-09-01",
            "pmSceneId": "scene-42",
            "caseId": "case-42",
        },)
        self.project_id = "project-7"

    def get_context(self, project_id):
        self.events.append(("context", project_id))
        return TeacherPlatformContext(
            project={"projectId": self.project_id},
            cases=self.cases, market_system={},
            units=(
                {"unitId": "G30", "key": "G30"},
                {"unitId": "G31", "key": "G31"},
            ),
        )

    def get_scene_unit_constraints(self, *, scene_id, page_no, page_size):
        self.events.append(("calculation", scene_id, page_no, page_size))
        return self.calc

    def get_unit_initial_state_inputs(
        self, *, scene_id, project_id, case_id, page_no, page_size
    ):
        self.events.append((
            "initial", scene_id, project_id, case_id, page_no, page_size
        ))
        return self.initial

    def save_unit_bid(self, *args, **kwargs):
        raise AssertionError("Writing a PMSS bid is forbidden")

    def run_clearing(self, *args, **kwargs):
        raise AssertionError("Executing PMSS clearing is forbidden")


def _export(fake, market=None, **kwargs):
    return collect_same_case_scene_evidence(
        fake, _synthetic_network_case() if market is None else market,
        project_id=kwargs.pop("project_id", "project-7"),
        case_date=kwargs.pop("case_date", "2025-09-01"),
        **kwargs,
    )


def test_one_explicit_day_only_uses_approved_readonly_scene_routes():
    fake = ReadOnlyFake()
    original = _synthetic_network_case()
    copied = deepcopy(original)
    result = _export(fake, market=original)
    assert original == copied
    assert fake.events == [
        ("context", "project-7"),
        ("calculation", "scene-42", 1, 999),
        ("initial", "scene-42", "project-7", "case-42", 1, 999),
    ]
    evidence = result["sceneConstraintEvidence"]
    assert evidence["constraintRows"] == 2
    assert evidence["initialRows"] == 2
    assert evidence["jointMilpReady"] is False
    assert result["evidenceBinding"]["sceneAssociation"] == (
        "operator_attested_case_date"
    )
    matched = verify_pmss_evidence_binding(result)
    assert matched["content_digests_matched"] is True
    assert matched["teacher_platform_source_authenticated"] is False
    assert matched["teacher_physical_semantics_verified"] is False
    assert "initialState" in json.dumps(evidence)


def test_bad_local_case_date_and_existing_binding_block_without_network():
    fake = ReadOnlyFake()
    wrong = _synthetic_network_case()
    wrong["caseDate"] = "2025-09-02"
    with pytest.raises(ValueError, match="matching case"):
        _export(fake, market=wrong)
    assert fake.events == []
    existing = _export(fake)
    fake.events.clear()
    with pytest.raises(ValueError, match="Already-attached"):
        _export(fake, market=existing)
    assert fake.events == []


def test_project_generator_identity_mismatch_rejected_before_scene_queries():
    class WrongGeneratorContext(ReadOnlyFake):
        def get_context(self, project_id):
            context = super().get_context(project_id)
            return TeacherPlatformContext(
                project=context.project,
                cases=context.cases,
                market_system=context.market_system,
                units=({"unitId": "G30"}, {"unitId": "NOT_THE_SAME_UNIT"}),
            )

    fake = WrongGeneratorContext()
    with pytest.raises(ValueError, match="generator IDs differ"):
        _export(fake)
    assert not any(e[0] in {"calculation", "initial"} for e in fake.events)


@pytest.mark.parametrize("mode", ["wrong_project", "missing_day", "ambiguous_day",
                                  "missing_scene", "missing_case"])
def test_wrong_project_or_ambiguous_case_never_runs_any_scene_query(mode):
    fake = ReadOnlyFake()
    if mode == "wrong_project":
        fake.project_id = "unexpected-project"
    elif mode == "missing_day":
        fake.cases = ()
    elif mode == "ambiguous_day":
        fake.cases = fake.cases * 2
    else:
        case = dict(fake.cases[0])
        case.pop("pmSceneId" if mode == "missing_scene" else "caseId")
        fake.cases = (case,)
    with pytest.raises(ValueError):
        _export(fake)
    assert not any(e[0] in {"calculation", "initial"} for e in fake.events)


@pytest.mark.parametrize("part", ["calculation", "initial"])
def test_truncated_readonly_pages_are_rejected_without_partial_output(part):
    fake = ReadOnlyFake()
    response = fake.calc if part == "calculation" else fake.initial
    response["rowCount"] += 1
    with pytest.raises(ValueError, match="pagination incomplete"):
        _export(fake)


def test_empty_scene_source_is_not_treated_as_confirmed_case_data():
    fake = ReadOnlyFake()
    fake.initial = {"rowCount": 0, "datas": []}
    with pytest.raises(ValueError, match="no rows"):
        _export(fake)


def test_invalid_project_identifier_is_rejected_before_any_api_call():
    fake = ReadOnlyFake()
    with pytest.raises(ValueError, match="characters"):
        _export(fake, project_id="project-7?token=never")
    assert fake.events == []


def test_expired_application_session_is_distinct_from_vpn_transport():
    class ExpiredFake(ReadOnlyFake):
        def get_context(self, project_id):
            raise TeacherPlatformAuthenticationExpired("T000")

    with pytest.raises(TeacherPlatformAuthenticationExpired):
        _export(ExpiredFake())


def test_cli_exports_only_new_private_0600_file_and_preserves_input(tmp_path, monkeypatch):
    from scripts import export_pmss_scene_evidence as cli

    fake = ReadOnlyFake()
    monkeypatch.setattr(cli, "TeacherPlatformAdapter", lambda **kw: fake)
    cookie_path = tmp_path/"private-cookies.json"
    cookie_path.write_text(json.dumps({"authenticated": "opaque-test"}))
    cookie_path.chmod(0o600)
    historical = tmp_path/"market.json"
    historic = _synthetic_network_case()
    historical.write_text(json.dumps(historic))
    out = tmp_path/"attached.json"
    monkeypatch.setenv("PMSS_BASE_URL", "https://example.test")
    monkeypatch.setenv("PMSS_COOKIE_FILE", str(cookie_path))
    argv = [
        "--snapshot", str(historical),
        "--project-id", "project-7", "--case-date", "2025-09-01",
        "--output", str(out),
    ]
    assert cli.main(argv) == 0
    assert out.stat().st_mode & 0o777 == 0o600
    result = json.loads(out.read_text())
    assert verify_pmss_evidence_binding(result)["content_digests_matched"]
    assert "opaque-test" not in out.read_text()
    assert json.loads(historical.read_text()) == historic
    previous_bytes = out.read_bytes()
    with pytest.raises(SystemExit):
        cli.main(argv)  # refusal to overwrite existing output
    assert out.read_bytes() == previous_bytes
    assert os.path.exists(historical)


def test_cli_expired_session_refuses_output_and_prints_no_credentials(
    tmp_path, monkeypatch, capsys,
):
    from scripts import export_pmss_scene_evidence as cli

    class ExpiredFake(ReadOnlyFake):
        def get_context(self, project_id):
            raise TeacherPlatformAuthenticationExpired("PRIVATE SECRET T000")

    monkeypatch.setattr(cli, "TeacherPlatformAdapter", lambda **kw: ExpiredFake())
    cookie = tmp_path/"cookie.json"
    cookie.write_text(json.dumps({"auth": "PRIVATE SECRET"}))
    cookie.chmod(0o600)
    historical = tmp_path/"market.json"
    historical.write_text(json.dumps(_synthetic_network_case()))
    output = tmp_path/"out.json"
    monkeypatch.setenv("PMSS_BASE_URL", "https://example.test")
    monkeypatch.setenv("PMSS_COOKIE_FILE", str(cookie))
    status = cli.main([
        "--snapshot", str(historical), "--project-id", "project-7",
        "--case-date", "2025-09-01", "--output", str(output),
    ])
    captured = capsys.readouterr()
    assert status == 3
    assert not output.exists()
    assert "session expired" in captured.err
    assert "PRIVATE SECRET" not in captured.err


def test_cli_rejects_world_readable_auth_cookie(tmp_path, monkeypatch):
    from scripts import export_pmss_scene_evidence as cli

    cookie = tmp_path/"cookie.json"
    cookie.write_text(json.dumps({"auth": "secret"}))
    cookie.chmod(0o644)
    source = tmp_path/"snapshot.json"
    source.write_text(json.dumps(_synthetic_network_case()))
    output = tmp_path/"result.json"
    monkeypatch.setenv("PMSS_BASE_URL", "https://example.test")
    monkeypatch.setenv("PMSS_COOKIE_FILE", str(cookie))
    assert cli.main([
        "--snapshot", str(source), "--project-id", "project-7",
        "--case-date", "2025-09-01", "--output", str(output),
    ]) == 4
    assert not output.exists()
