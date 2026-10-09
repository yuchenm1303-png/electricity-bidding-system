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
    for row, mw in zip(case["results"]["unitResults"], generation, strict=True):
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
    assert a["secondaryOptimizationCostToleranceAbs"] == 1e-6
    assert a["secondaryOptimizationCostToleranceRel"] == 1e-10
    assert a["maximumObservedSecondaryCostDifference"] >= 0
    assert a["maximumObservedSecondaryCostDifference"] < 1e-3
    assert a["validatedNewBids"] is False
    assert a["pmssWritePerformed"] is False
    assert a["profitPredictionVerified"] is False
    assert a["identicalOriginalBidPairsAcrossDates"] == 3
    # Change ONLY held-out observations. The selected rule must not change.
    for row, mw in zip(cases[2]["results"]["unitResults"], (10.0, 150.0), strict=True):
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



def test_three_day_result_shows_day_paired_risks_and_reused_original_offers():
    cases = _triple()
    original = evaluate_heldout_tiebreak_rules(cases)
    assert original["trainingDistinctOriginalBidCurves"] == 1
    assert original["holdoutDatesReusingTrainingBidCurves"] == 1
    assert original["holdoutDistinctOriginalBidCurves"] == 1
    assert len(original["trainingDailyDiagnostics"]) == 2
    assert len(original["holdoutDailyDiagnostics"]) == 1
    assert original["holdoutRobustnessAssessment"] == (
        "ONLY_ONE_HOLDOUT_DATE_NO_STATISTICAL_CONFIDENCE"
    )
    assert not original["statisticalSignificanceEstablished"]
    assert not original["readyForForwardBidOptimization"]
    assert not original["predeclaredTrainingGuardrail"]["passed"]
    assert (
        "TRAINING_OFFER_DIVERSITY_LT_2" in
        original["predeclaredTrainingGuardrail"]["reasons"]
    )
    assert all(
        day["caseDate"] == f"2025-09-0{i}"
        for i, day in enumerate(
            original["trainingDailyDiagnostics"] +
            original["holdoutDailyDiagnostics"], 1
        )
    )
    assert original["largestHoldoutDeteriorationMaeMw"] == pytest.approx(0)


def test_training_guardrail_uses_no_holdout_labels_or_offer_novelty(monkeypatch):
    from types import SimpleNamespace

    import powerbid.pmss_tiebreak_holdout as module

    samples = _triple()
    # Different offer segment boundaries but identical marginal offer prices.
    # For this isolated selection test, mock the heavy local LP study.
    samples[1]["unitBids"]["G2"]["datas"][0]["segmentDatas"] = [
        {"startPower": 0, "endPower": 75, "price": 90, "segmentOrder": 1},
        {"startPower": 75, "endPower": 150, "price": 90, "segmentOrder": 2},
    ]
    def fake_study(raw):
        heldout = raw["caseDate"] == "2025-09-03"
        return SimpleNamespace(
            compared_hours=24,
            examined_hours=24,
            generator_count=2,
            canonical_order_baseline_mae_mw=20.0,
            ascending_dispatch_mae_mw=40.0 if heldout else 10.0,
            descending_dispatch_mae_mw=5.0 if heldout else 30.0,
            source_order_baseline_mae_mw=20.0,
        )

    monkeypatch.setattr(module, "audit_historical_tiebreaks", fake_study)
    a = evaluate_heldout_tiebreak_rules(samples)
    assert a["policyLockedUsingTrainingOnly"] == "unit_id_ascending"
    assert a["predeclaredTrainingGuardrail"]["passed"]
    assert a["predeclaredTrainingGuardrail"][
        "trainingOnlyConservativeComparator"
    ] == "unit_id_ascending"
    assert a["trainingDistinctOriginalBidCurves"] == 2
    assert a["holdoutDatesReusingTrainingBidCurves"] == 1
    assert a["holdoutMaeMwByPolicy"]["unit_id_ascending"] == pytest.approx(40)
    assert a["largestHoldoutDeteriorationMaeMw"] == pytest.approx(20)
    assert a["holdoutSelectedDaysBetterThanCanonical"] == 0
    assert a["trainingSelectedDaysBetterThanCanonical"] == 2
    assert a["selectionUsesHoldoutObservations"] is False
    # Change held-out observations in the mocked study. The training choice
    # and predeclared guardrail MUST remain unchanged.
    def alternate_holdout(raw):
        study = fake_study(raw)
        if raw["caseDate"] == "2025-09-03":
            study.ascending_dispatch_mae_mw = 0.1
            study.descending_dispatch_mae_mw = 100
        return study
    monkeypatch.setattr(module, "audit_historical_tiebreaks", alternate_holdout)
    b = evaluate_heldout_tiebreak_rules(samples)
    assert b["policyLockedUsingTrainingOnly"] == a["policyLockedUsingTrainingOnly"]
    assert b["predeclaredTrainingGuardrail"] == a["predeclaredTrainingGuardrail"]
    assert b["holdoutMaeMwByPolicy"] != a["holdoutMaeMwByPolicy"]


def test_minimum_material_training_margin_must_be_valid_and_declared():
    for threshold in (0, -1, True, float("nan"), float("inf"), 101, "5"):
        with pytest.raises(ValueError, match="training improvement"):
            evaluate_heldout_tiebreak_rules(
                _triple(), min_training_improvement_mw=threshold
            )


def test_two_heldout_days_are_reported_as_descriptive_not_statistical():
    samples = [_fixture(f"2025-09-0{d}") for d in range(1, 5)]
    report = evaluate_heldout_tiebreak_rules(samples, holdout_dates=2)
    assert report["trainingCaseCount"] == 2
    assert report["holdoutCaseCount"] == 2
    assert report["holdoutRobustnessAssessment"] == (
        "DESCRIPTIVE_MULTIDAY_HOLDOUT_NO_STATISTICAL_CONFIDENCE"
    )
    assert len(report["holdoutDailyDiagnostics"]) == 2
    assert report["statisticalSignificanceEstablished"] is False
    assert report["holdoutDatesReusingTrainingBidCurves"] == 2
