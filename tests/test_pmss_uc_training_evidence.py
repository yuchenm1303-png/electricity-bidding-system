"""Synthetic tests for private PMSS scenario/temporal training-only evidence."""
import json

import pytest
from test_historical_validation import _fixture

import powerbid.pmss_uc_training_evidence as module


def _scene(units=("G1", "G2")):
    rows = [
        {
            "unitId": uid, "sceneId": "same-scene",
            "ifConRamp": 1,
            "ifConEnergy": 0,
            "ifConInitPower": 1,
            "ifConUpDnTimes": 0,
            "ifConMinOnOffTm": 0,
            "ifConStartCost": 1,
            "ifConNoloadCost": 1,
        }
        for uid in units
    ]
    return {
        "calculation": {
            "http": 200,
            "code": "T200",
            "data": {
                "pageNum": 1, "totalPage": 1,
                "rowCount": len(rows), "datas": rows,
            },
        },
        "initial": {
            "error": "opaque GET error potentially containing sensitive data"
        },
    }


def _cases():
    return [_fixture("2025-09-01"), _fixture("2025-09-02")]


def _audit(cases=None, scene=None):
    return module.audit_training_scene_and_temporal_evidence(
        _cases() if cases is None else cases,
        _scene() if scene is None else scene,
        holdout_start_date="2025-09-03",
    )


def test_complete_training_replay_and_structural_source_evidence_is_not_uc_proof():
    report = _audit()
    assert report["status"] == "OBSERVED_TRAINING_SCENE_UC_READINESS_BLOCKED"
    assert report["trainingCaseDates"] == ["2025-09-01", "2025-09-02"]
    assert report["heldoutStartDate"] == "2025-09-03"
    assert report["holdoutObservedDispatchRead"] is False
    assert report["sceneUnitIdentityMatchesHistoricalBids"] is True
    assert report["initialStateIndependentT200Complete"] is False
    assert report["independentlyAuthenticatedSameCase"] is False
    assert report["rawSwitchCodeCounts"]["ifConRamp"]["code_1"] == 2
    assert "INDEPENDENT_INITIAL_STATE_PAGE_UNAVAILABLE" in report["unresolvedUcEvidence"]
    assert report["thermalConstraintsProduced"] is False
    assert report["jointMilpReady"] is False
    assert not report["trainedPredictiveUcModel"]
    assert not report["validatedNewBidRevenue"]
    assert report["pmssWritePerformed"] is False
    for item in report["hourlyObservations"]:
        assert item["expectedAdjacentUnitPairs"] == 46
        assert item["observedAdjacentUnitPairs"] == 46
        assert item["missingAdjacentUnitPairs"] == 0
        assert item["pairedDeltaDifferenceMaeMw"] == pytest.approx(0, abs=1e-7)
        assert item["pairedDeltaDifferenceMaxMw"] == pytest.approx(0, abs=1e-7)
    serialized = json.dumps(report)
    assert '"G1"' not in serialized
    assert '"G2"' not in serialized
    assert "same-scene" not in serialized
    assert "opaque GET error" not in serialized
    assert "unitId" not in serialized
    assert "unitBids" not in serialized


def test_training_observed_delta_deviation_is_only_a_historical_diagnostic():
    cases = _cases()
    cases[0]["results"]["unitResults"][0]["accepted_mw"][1] += 15
    result = _audit(cases)
    day = result["hourlyObservations"][0]
    assert day["pairedDeltaDifferenceMaeMw"] == pytest.approx(30 / 46)
    assert day["pairedDeltaDifferenceMaxMw"] == pytest.approx(15)
    assert result["jointMilpReady"] is False


def test_future_and_holdout_snapshots_blocked_before_observation_replay(monkeypatch):
    def never_replay(*args, **kwargs):
        pytest.fail("Future observations must never be replayed")

    monkeypatch.setattr(module, "_temporal_training_day", never_replay)
    with pytest.raises(ValueError, match="Holdout or future"):
        _audit([*_cases(), _fixture("2025-09-03")])
    with pytest.raises(ValueError, match="Duplicate"):
        sample = _cases()[0]
        _audit([sample, sample])


def test_source_t000_http200_and_mismatched_units_are_rejected():
    capture = _scene()
    capture["calculation"]["code"] = "T000"
    with pytest.raises(ValueError, match="T200"):
        _audit(scene=capture)
    capture = _scene()
    capture["calculation"]["data"]["rowCount"] = 1
    with pytest.raises(ValueError, match="incomplete"):
        _audit(scene=capture)
    capture = _scene(("G1", "G999"))
    with pytest.raises(ValueError, match="identities"):
        _audit(scene=capture)
    capture = _scene()
    capture["calculation"]["data"]["datas"][1]["sceneId"] = "second-scene"
    with pytest.raises(ValueError, match="scene origin"):
        _audit(scene=capture)


def test_missing_units_and_corrupted_independent_initial_page_cannot_pass():
    capture = _scene()
    capture["initial"] = {
        "http": 200, "code": "T200",
        "data": {"pageNum": 1, "totalPage": 1, "rowCount": 2,
                 "datas": [{"unitId": "G1"}, {"unitId": "UNRELATED"}]},
    }
    with pytest.raises(ValueError, match="identities"):
        _audit(scene=capture)
    capture["initial"]["data"]["datas"][1]["unitId"] = "G2"
    with pytest.raises(ValueError, match="required fields"):
        _audit(scene=capture)
    for row in capture["initial"]["data"]["datas"]:
        row.update({
            "initialState": 10, "keepTime": 0, "power": 0,
            "downStatus": 1, "minOnTime": 0, "minOffTime": 0,
        })
    report = _audit(scene=capture)
    assert report["initialStateIndependentT200Complete"] is True
    assert report["jointMilpReady"] is False
    assert "INITIAL_ON_OFF_STATE_SEMANTICS_UNVERIFIED" in report["unresolvedUcEvidence"]


def test_missing_historical_point_is_not_zero_and_drift_is_rejected():
    cases = _cases()
    cases[0]["results"]["unitResults"][0]["accepted_mw"][3] = None
    report = _audit(cases)
    assert report["hourlyObservations"][0]["missingAdjacentUnitPairs"] == 2
    assert report["hourlyObservations"][0]["observedAdjacentUnitPairs"] == 44
    drift = _cases()
    drift[1]["dcNetwork"]["lines"][0]["limitMw"] += 1
    with pytest.raises(ValueError, match="network"):
        _audit(drift)


def test_later_date_original_results_cannot_affect_frozen_training_audit():
    earlier = _cases()
    first = _audit(earlier)
    unrelated_future = _fixture("2025-09-03")
    unrelated_future["results"]["unitResults"][0]["accepted_mw"] = [0] * 24
    assert _audit(earlier) == first
    with pytest.raises(ValueError, match="Holdout or future"):
        _audit([*earlier, unrelated_future])
