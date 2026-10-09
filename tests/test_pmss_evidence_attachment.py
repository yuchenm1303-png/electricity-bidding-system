"""Case-attested PMSS evidence only: digest integrity without claiming truth."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from test_pmss_scene_constraint_evidence import fixture as scene_fixture
from test_pmss_web_api import _synthetic_network_case

from powerbid.pmss_evidence_attachment import (
    attach_pmss_evidence,
    verify_pmss_evidence_binding,
)
from powerbid.pmss_scene_constraint_evidence import summarize_scene_constraint_evidence


def _original():
    return _synthetic_network_case()


def _grid():
    case = _original()
    return {"units": {"datas": [{
        "id": item["key"],
        "pdAdjustMax": item["pdAdjustMax"],
        "minCapacity": item["pdAdjustMin"],
        "incRate": 20, "decRate": 20,
        "minOnTime": 0, "minOffTime": 0, "launchCost": 0,
        "cookie": "NEVER_EXPORT_THIS_PRIVATE_VALUE",
    } for item in case["unitTree"]]}}


def _scene():
    calc, initial = scene_fixture()
    return summarize_scene_constraint_evidence(calc, initial, expected_units=2)


def _attach(**kwargs):
    return attach_pmss_evidence(_original(), **kwargs)


def test_verified_generator_id_join_is_separate_from_unverified_pmss_semantics():
    result = _attach(private_grid=_grid())
    binding = result["evidenceBinding"]
    assert binding["caseDate"] == "2025-09-01"
    assert binding["technicalAssociation"] == "exact_unit_id_join"
    assert binding["sceneAssociation"] == "absent"
    assert binding["independentlyVerified"] is False
    assert len(binding["technicalSha256"]) == 64
    audit = verify_pmss_evidence_binding(result)
    assert audit["content_digests_matched"] is True
    assert audit["teacher_platform_source_authenticated"] is False
    assert audit["model_technical_parameters_verified"] is False
    assert "NEVER_EXPORT_THIS_PRIVATE_VALUE" not in json.dumps(result)
    assert "G30" not in json.dumps(result["technicalEvidence"])


def test_scene_case_attestation_must_be_explicit_and_not_auto_certified():
    with pytest.raises(ValueError, match="Case date"):
        _attach(scene_summary=_scene())
    with pytest.raises(ValueError, match="differs"):
        _attach(
            scene_summary=_scene(), scene_case_date="2025-09-02",
            scene_source_note="case report provided by operator",
        )
    report = _attach(
        private_grid=_grid(),
        scene_summary=_scene(), scene_case_date="2025-09-01",
        scene_source_note="PMSS case date checked against authorized read-only query",
    )
    audit = verify_pmss_evidence_binding(report)
    assert audit["scene_association"] == "operator_attested_case_date"
    assert audit["teacher_platform_source_authenticated"] is False
    assert "initialState" in str(report["sceneConstraintEvidence"])
    assert '"on"' not in json.dumps(report["sceneConstraintEvidence"])


def test_digest_mismatch_and_case_label_changes_are_detected_without_false_proof():
    both = _attach(
        private_grid=_grid(), scene_summary=_scene(),
        scene_case_date="2025-09-01",
        scene_source_note="PMSS case date verified by operator for lesson",
    )
    altered = deepcopy(both)
    altered["technicalEvidence"]["observedFields"]["incRate"]["min"] = 1
    with pytest.raises(ValueError, match="digest"):
        verify_pmss_evidence_binding(altered)
    altered = deepcopy(both)
    altered["sceneConstraintEvidence"]["constraintRows"] = 1
    with pytest.raises(ValueError, match="digest"):
        verify_pmss_evidence_binding(altered)
    altered = deepcopy(both)
    altered["caseDate"] = "2025-09-02"
    with pytest.raises(ValueError, match="another"):
        verify_pmss_evidence_binding(altered)
    altered = deepcopy(both)
    altered["evidenceBinding"]["independentlyVerified"] = True
    with pytest.raises(ValueError, match="cannot assert"):
        verify_pmss_evidence_binding(altered)


def test_unknown_root_secret_and_misjoined_generator_are_blocked():
    sample = _original()
    sample["token"] = "PRIVATE"
    with pytest.raises(ValueError, match="unknown"):
        attach_pmss_evidence(sample, private_grid=_grid())
    sample = _original()
    sample["unitBids"]["G30"]["datas"][0]["password"] = "SECRET"
    with pytest.raises(ValueError, match="credential"):
        attach_pmss_evidence(sample, private_grid=_grid())
    altered = _grid()
    altered["units"]["datas"][0]["id"] = "UNKNOWN"
    with pytest.raises(ValueError, match="IDs"):
        _attach(private_grid=altered)


def test_legacy_scene_summary_needs_explicit_attested_case_date():
    from powerbid.pmss_integration import snapshot_from_pmss
    from powerbid.pmss_technical_evidence import sanitize_pmss_technical_evidence
    market = _original()
    snapshot = snapshot_from_pmss(
        unit_tree=market["unitTree"], unit_bids=market["unitBids"],
        market_system=market["marketSystem"],
        demand_forecast_mw=market["demandForecastMw"],
        forecast_source=market["forecastSource"],
    )
    market["technicalEvidence"] = sanitize_pmss_technical_evidence(
        _grid(), snapshot=snapshot
    )
    market["sceneConstraintEvidence"] = _scene()
    with pytest.raises(ValueError, match="Case date"):
        attach_pmss_evidence(market)
    attached = attach_pmss_evidence(
        market, scene_case_date="2025-09-01",
        scene_source_note="Explicit operator case and scene association note",
    )
    assert attached["evidenceBinding"]["technicalAssociation"] == "legacy_summary_only"


def test_cli_writes_only_new_0600_snapshot_and_never_overwrites(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    script = repo / "scripts/attach_pmss_evidence.py"
    market = tmp_path/"market.json"
    grid = tmp_path/"grid.json"
    scene = tmp_path/"scene.json"
    output = tmp_path/"case-bound.json"
    for name, data in ((market, _original()), (grid, _grid()), (scene, _scene())):
        name.write_text(json.dumps(data), encoding="utf-8")
    cmd = [
        sys.executable, str(script), "--snapshot", str(market),
        "--technical-grid", str(grid), "--scene-summary", str(scene),
        "--scene-case-date", "2025-09-01",
        "--scene-source-note", "Trusted operator matched scene source to course case",
        "--output", str(output),
    ]
    first = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert output.stat().st_mode & 0o777 == 0o600
    body = json.loads(output.read_text(encoding="utf-8"))
    assert verify_pmss_evidence_binding(body)["content_digests_matched"]
    assert "NEVER_EXPORT_THIS_PRIVATE_VALUE" not in output.read_text()
    before = output.read_bytes()
    again = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert again.returncode != 0
    assert output.read_bytes() == before
    assert "PRIVATE" not in first.stdout
    assert os.path.isfile(market)



def test_inspect_rejects_tampered_casebound_evidence_without_disclosing_source():
    from fastapi.testclient import TestClient

    from app.web_server import app
    client = TestClient(app)
    file = _attach(
        private_grid=_grid(), scene_summary=_scene(),
        scene_case_date="2025-09-01",
        scene_source_note="Course case identity was attested by authorized operator",
    )
    response = client.post("/api/pmss/inspect", json={"snapshot": file})
    assert response.status_code == 200, response.text
    status = response.json()["evidence_binding"]
    assert status["content_digests_matched"] is True
    assert status["teacher_platform_source_authenticated"] is False
    assert status["teacher_physical_semantics_verified"] is False
    assert status["model_technical_parameters_verified"] is False
    assert "Course case identity was attested" not in response.text
    bad = deepcopy(file)
    bad["technicalEvidence"]["observedFields"]["launchCost"]["max"] = 14
    rejected = client.post("/api/pmss/inspect", json={"snapshot": bad})
    assert rejected.status_code == 422
    assert "digest" in rejected.text
    changed_date = deepcopy(file)
    changed_date["caseDate"] = "2025-09-02"
    assert client.post("/api/pmss/inspect", json={
        "snapshot": changed_date,
    }).status_code == 422
