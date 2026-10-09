"""Freeze a historical tie-break rule before evaluating untouched later dates."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_historical_validation import _fixture

from powerbid.pmss_tiebreak_holdout import evaluate_heldout_tiebreak_rules


def _triple():
    return [_fixture(f"2025-09-0{day}") for day in (1, 2, 3)]


def _switch_to_tied_market(case, *, favor: str):
    # Generator G1 at A, G2 at B. Collapse the topology to one equal-price
    # bus and set original historical outcomes to opposite optimal corners.
    # This is SYNTHETIC, not PMSS's actual clearing convention.
    case["dcNetwork"]["buses"] = ["B"]
    case["dcNetwork"]["lines"] = []
    case["dcNetwork"]["unitBus"] = {"G1": "B", "G2": "B"}
    case["dcNetwork"]["hourlyDemandMw"] = {"B": [160.0]*24}
    case["dcNetwork"]["slackBus"] = "B"
    case["unitBids"]["G2"]["datas"][0]["segmentDatas"][0]["price"] = 60
    generation = (100.0, 60.0) if favor == "ascending" else (10.0, 150.0)
    for row, mw in zip(case["results"]["unitResults"], generation):
        row["accepted_mw"] = [mw]*24
    # No line results are required by the tie-break allocation experiment.


def test_three_days_keeps_holdout_rule_choice_independent_of_future_labels():
    cases = _triple()
    for row in cases[:2]:
        _switch_to_tied_market(row, favor="descending")
    _switch_to_tied_market(cases[2], favor="ascending")
    a = evaluate_heldout_tiebreak_rules(cases)
    assert a["trainingCaseDates"] == ["2025-09-01", "2025-09-02"]
    assert a["untouchedHoldoutCaseDates"] == ["2025-09-03"]
    # Canonical LP may itself pick the descending extreme; the fixed
    # policy tie order then selects canonical rather than descending.
    assert a["policyLockedUsingTrainingOnly"] in ("canonical_lp", "unit_id_descending")
    assert a["holdoutBestPolicyExPostDiagnosticOnly"] == "unit_id_ascending"
    assert a["trainingMaeMwByPolicy"]["unit_id_descending"] == pytest.approx(0, abs=.002)
    assert a["holdoutMaeMwByPolicy"]["unit_id_ascending"] == pytest.approx(0, abs=.002)
    assert a["holdoutMaeMwByPolicy"]["unit_id_descending"] > 50
    assert a["selectionUsesHoldoutObservations"] is False
    assert a["validatedNewBids"] is False
    assert a["pmssWritePerformed"] is False
    assert a["profitPredictionVerified"] is False
    assert a["identicalOriginalBidPairsAcrossDates"] == 3
    # Change ONLY held-out observations. The selected rule must not change.
    for row, mw in zip(cases[2]["results"]["unitResults"], (10.0, 150.0)):
        row["accepted_mw"] = [mw]*24
    changed = evaluate_heldout_tiebreak_rules(cases)
    assert changed["policyLockedUsingTrainingOnly"] == a["policyLockedUsingTrainingOnly"]
    assert changed["holdoutMaeMwByPolicy"] != a["holdoutMaeMwByPolicy"]


def test_permuted_case_input_still_uses_calendar_order():
    cases = _triple()
    expected = evaluate_heldout_tiebreak_rules(cases)
    reordered = evaluate_heldout_tiebreak_rules(list(reversed(cases)))
    assert expected == reordered
    assert expected["identicalOriginalBidPairsAcrossDates"] == 3
    assert expected["status"] == "CHRONOLOGICAL_HOLDOUT_ORIGINAL_BID_RESEARCH_ONLY"


def test_duplicate_date_changed_grid_and_insufficient_days_are_rejected():
    cases = _triple()
    with pytest.raises(ValueError, match="3..12"):
        evaluate_heldout_tiebreak_rules(cases[:2])
    with pytest.raises(ValueError, match="holdout"):
        evaluate_heldout_tiebreak_rules(cases, holdout_dates=2)
    cases[2]["caseDate"] = cases[1]["caseDate"]
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_heldout_tiebreak_rules(cases)
    cases = _triple()
    cases[2]["dcNetwork"]["lines"][0]["limitMw"] += 1
    with pytest.raises(ValueError, match="Grid"):
        evaluate_heldout_tiebreak_rules(cases)


def test_missing_unit_history_blocks_false_holdout_success():
    cases = _triple()
    cases[2]["results"]["unitResults"][0]["accepted_mw"][0] = None
    with pytest.raises(ValueError, match="complete"):
        evaluate_heldout_tiebreak_rules(cases)
    cases = _triple()
    cases[0]["results"]["unitResults"][0]["accepted_mw"][0] = None
    with pytest.raises(ValueError, match="24 observed"):
        evaluate_heldout_tiebreak_rules(cases)


def test_different_original_offer_curves_are_reported_as_diversity():
    cases = _triple()
    cases[2]["unitBids"]["G2"]["datas"][0]["segmentDatas"][0]["price"] += 10
    report = evaluate_heldout_tiebreak_rules(cases)
    assert report["identicalOriginalBidPairsAcrossDates"] == 1


def test_source_secrets_and_generator_ids_cannot_escape_anonymous_report():
    cases = _triple()
    cases[0]["secretCustomValue"] = "CONFIDENTIAL_SOURCE_VALUE"
    cases[1]["projectId"] = "PROJECT_CONFIDENTIAL"
    data = json.dumps(evaluate_heldout_tiebreak_rules(cases))
    assert "CONFIDENTIAL_SOURCE_VALUE" not in data
    assert "PROJECT_CONFIDENTIAL" not in data
    assert '"unit_id"' not in data
    assert '"G1"' not in data


def test_cli_private_nonoverwriting_heldout_report(tmp_path):
    cases = _triple()
    paths = []
    for row in cases:
        name = tmp_path / (row["caseDate"] + ".json")
        name.write_text(json.dumps(row), encoding="utf-8")
        paths.append(name)
    output = tmp_path / "heldout.json"
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] /
            "scripts/report_pmss_tiebreak_holdout.py"),
        "--output", str(output),
        *(str(path) for path in paths),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=100)
    assert result.returncode == 0, result.stderr
    assert output.stat().st_mode & 0o777 == 0o600
    encoded = output.read_text()
    assert json.loads(encoded)["validatedNewBids"] is False
    assert "G1" not in encoded
    repeat = subprocess.run(cmd, capture_output=True, text=True, timeout=100)
    assert repeat.returncode != 0
