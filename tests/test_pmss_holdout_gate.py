"""Anonymous PMSS report arithmetic validation and no-live safeguards."""
from __future__ import annotations

from copy import deepcopy

import pytest
from test_pmss_tiebreak_holdout import _triple

from powerbid.pmss_holdout_gate import review_holdout_report
from powerbid.pmss_tiebreak_holdout import evaluate_heldout_tiebreak_rules


@pytest.fixture(scope="module")
def generated():
    return evaluate_heldout_tiebreak_rules(_triple())


def test_generated_report_is_still_only_descriptive(generated):
    review = review_holdout_report(generated)
    assert review["status"] == "TRAINING_GUARD_BLOCKED"
    assert review["researchOnly"] is True
    assert review["liveBidAllowed"] is False
    assert review["sourceAuthenticatedByThisReport"] is False
    assert review["pmssCounterfactualValidated"] is False
    assert review["profitForecastValidated"] is False
    assert review["statisticalConfidenceEstablished"] is False
    assert review["lockedConservativeComparator"] == "canonical_lp"
    assert review["canonicalHoldoutMaeMw"] == pytest.approx(
        review["conservativeHoldoutMaeMw"]
    )
    assert review["conservativeHoldoutDeltaMaeMw"] == pytest.approx(0)
    assert review["holdoutDatesReusingTrainingOffers"] == 1
    assert review["distinctTrainingBidCurves"] == 1


@pytest.mark.parametrize("mutation", [
    lambda r: r["trainingMaeMwByPolicy"].update({"unit_id_ascending": 0}),
    lambda r: r["holdoutDailyDiagnostics"][0]["maeMwByPolicy"].update(
        {"unit_id_descending": 999}
    ),
    lambda r: r["predeclaredTrainingGuardrail"].update({"passed": True}),
    lambda r: r["predeclaredTrainingGuardrail"].update({"reasons": []}),
    lambda r: r.update({"policyLockedUsingTrainingOnly": "unit_id_descending"}),
    lambda r: r["holdoutDailyDiagnostics"][0].update({
        "guardedVsCanonicalDeltaMaeMw": 12,
    }),
    lambda r: r.update({"trainingDates": ["2099-01-01"]}),
    lambda r: r.update({"liveBidAllowed": True}),
    lambda r: r.update({"validatedNewBids": True}),
    lambda r: r.update({"profitPredictionVerified": True}),
    lambda r: r.update({"pmssWritePerformed": True}),
    lambda r: r.update({"conservativeComparatorEligibleForLivePMSS": True}),
    lambda r: r["trainingCaseDates"].reverse(),
    lambda r: r["holdoutDailyDiagnostics"][0].update({"caseDate": "2025-09-02"}),
    lambda r: r.update({"holdoutDatesReusingTrainingBidCurves": 0}),
    lambda r: r.update({"holdoutConservativeComparatorMaeMw": float("nan")}),
    lambda r: r["predeclaredTrainingGuardrail"].update({
        "minimumMeaningfulImprovementMw": 0,
    }),
])
def test_tampering_wrong_date_or_false_certification_rejected(generated, mutation):
    report = deepcopy(generated)
    mutation(report)
    with pytest.raises(ValueError):
        review_holdout_report(report)


def test_api_accepts_aggregate_never_echoes_untrusted_text(generated):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app.web_server import app

    client = TestClient(app)
    report = deepcopy(generated)
    report["warning"] = "PRIVATE_UNTRUSTED_UPLOAD_TEXT"
    ok = client.post("/api/pmss/holdout-gate", json={"report": report})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["researchOnly"]
    assert body["liveBidAllowed"] is False
    assert "PRIVATE_UNTRUSTED_UPLOAD_TEXT" not in ok.text
    assert '"G1"' not in ok.text

    report["validatedNewBids"] = True
    rejected = client.post("/api/pmss/holdout-gate", json={"report": report})
    assert rejected.status_code == 422
    assert "PRIVATE_UNTRUSTED_UPLOAD_TEXT" not in rejected.text
    assert client.get("/api/pmss/holdout-gate").status_code == 405


def test_training_gate_pass_with_holdout_deterioration(monkeypatch):
    from types import SimpleNamespace

    import powerbid.pmss_tiebreak_holdout as module

    cases = _triple()
    cases[1]["unitBids"]["G2"]["datas"][0]["segmentDatas"] = [
        {"startPower": 0, "endPower": 75, "price": 90, "segmentOrder": 1},
        {"startPower": 75, "endPower": 150, "price": 90, "segmentOrder": 2},
    ]
    def fake_study(raw):
        heldout = raw["caseDate"] == "2025-09-03"
        return SimpleNamespace(
            compared_hours=24, examined_hours=24, generator_count=2,
            canonical_order_baseline_mae_mw=20.0,
            ascending_dispatch_mae_mw=40.0 if heldout else 10.0,
            descending_dispatch_mae_mw=30.0,
            source_order_baseline_mae_mw=20.0,
        )
    monkeypatch.setattr(module, "audit_historical_tiebreaks", fake_study)
    reviewed = review_holdout_report(evaluate_heldout_tiebreak_rules(cases))
    assert reviewed["status"] == "HOLDOUT_DETERIORATION_OBSERVED"
    assert reviewed["trainingGuardPassed"] is True
    assert reviewed["trainingWinner"] == "unit_id_ascending"
    assert reviewed["lockedConservativeComparator"] == "unit_id_ascending"
    assert reviewed["conservativeHoldoutDeltaMaeMw"] == pytest.approx(20)
    assert reviewed["conservativeWorstSingleDayDeteriorationMaeMw"] == pytest.approx(20)
    assert reviewed["liveBidAllowed"] is False
