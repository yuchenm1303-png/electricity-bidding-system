"""Three distinct PMSS case dates are descriptive evidence, never a bid certificate."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_historical_validation import _fixture

from powerbid.pmss_crossday_research import summarize_crossday_history


def _three():
    return [_fixture(f"2025-09-0{i}") for i in range(1, 4)]


def test_three_complete_days_report_same_support_without_claiming_pmss_profit():
    report = summarize_crossday_history(_three())
    assert report["status"] == "DESCRIPTIVE_HISTORICAL_RESEARCH_ONLY"
    assert report["independentDateCount"] == 3
    assert report["sameGridFingerprint"] is True
    assert report["latestDateHeldOutForDescriptiveComparison"] == "2025-09-03"
    assert report["noModelTrainingPerformed"] is True
    assert report["validatedNewBids"] is False
    assert report["teacherPlatformWritesPerformed"] is False
    assert report["actualPmssClearingExecuted"] is False
    for d in report["days"]:
        assert d["unitCount"] == 2
        assert d["nodeCount"] == 2
        assert d["branchCount"] == 1
        assert d["hourCount"] == 24
        assert d["originalBidDcUnitDispatchMaeMw"] == pytest.approx(0)
        assert d["originalBidDcNodePriceMae"] == pytest.approx(0)
        assert d["originalBidDcLineFlowAbsMaeMw"] == pytest.approx(0)
        assert d["fixedObservedDispatchLineFlowAbsMaeMw"] == pytest.approx(0, abs=1e-6)
        assert d["sameObservationSet"] is True
        assert d["unitDispatchCoverage"] == 1
        assert d["nodePriceCoverage"] == 1
        assert d["lineFlowCoverage"] == 1


def test_duplicate_date_and_insufficient_dates_rejected():
    with pytest.raises(ValueError, match="3..20"):
        summarize_crossday_history(_three()[:2])
    items = _three()
    items[-1]["caseDate"] = items[0]["caseDate"]
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_crossday_history(items)


def test_changed_grid_fingerprint_must_not_be_pooled():
    items = _three()
    items[2]["dcNetwork"]["lines"][0]["limitMw"] += 50
    with pytest.raises(ValueError, match="Topology changed"):
        summarize_crossday_history(items)


def test_missing_injections_never_create_false_comparable_flow_mae():
    items = _three()
    items[2]["results"]["unitResults"][0]["accepted_mw"][6] = None
    data = summarize_crossday_history(items)
    last = data["days"][-1]
    assert last["fixedObservedDispatchHours"] == 23
    assert last["sameObservationSet"] is False
    assert last["relativeLineFlowMaeFixedVsRecleared"] is None


def test_unknown_raw_source_fields_never_leak_from_aggregate_report():
    items = _three()
    items[0]["credentials"] = "EXAMPLE_PRIVATE_SECRET"
    items[0]["projectId"] = "DONT_EXPORT_PROJECT_IDENTIFIER"
    report = summarize_crossday_history(items)
    encoded = json.dumps(report)
    assert "EXAMPLE_PRIVATE_SECRET" not in encoded
    assert "DONT_EXPORT_PROJECT_IDENTIFIER" not in encoded
    assert "unit_id" not in encoded
    assert "element_id" not in encoded


def test_cli_creates_non_overwriting_private_aggregate(tmp_path):
    files = []
    for sample in _three():
        path = tmp_path / (sample["caseDate"] + ".json")
        path.write_text(json.dumps(sample), encoding="utf-8")
        files.append(path)
    dst = tmp_path / "report.json"
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts/report_pmss_crossday.py"),
        "--output", str(dst),
        *(str(f) for f in files),
    ]
    first = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    assert first.returncode == 0, first.stderr
    assert dst.stat().st_mode & 0o777 == 0o600
    assert json.loads(dst.read_text())["independentDateCount"] == 3
    repeat = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    assert repeat.returncode != 0
