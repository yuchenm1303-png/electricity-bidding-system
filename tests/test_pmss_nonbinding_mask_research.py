"""Forward-data-leakage and anonymization guards for ex-post zero masks."""
import json

import pytest
from test_historical_validation import _fixture

from powerbid.pmss_nonbinding_mask_research import (
    audit_training_only_nonbinding_masks,
)


def test_training_only_report_exposes_no_raw_units_and_not_live_safe():
    data = [_fixture("2025-09-01"), _fixture("2025-09-02")]
    report = audit_training_only_nonbinding_masks(
        data[::-1], holdout_start_date="2025-09-03",
    )
    assert report["trainingCaseDates"] == ["2025-09-01", "2025-09-02"]
    assert report["holdoutObservationsRead"] is False
    assert report["safeForForwardModelCalibration"] is False
    assert not report["physicalUnitOnOffStateVerified"]
    assert not report["validatedNewBids"]
    assert len(report["days"]) == 2
    assert len(report["days"][0]["hours"]) == 24
    assert report["days"][0]["nonbindingMaskHours"] == 0
    assert report["days"][0]["noZeroOutputMaskHours"] == 24
    assert report["days"][0]["nonbindingRedispatchHours"] == 0
    text = json.dumps(report)
    assert '"G1"' not in text
    assert '"G2"' not in text
    assert "unit_id" not in text
    assert "element_id" not in text
    assert "unitBids" not in text


def test_heldout_date_and_future_observations_cannot_enter_training():
    samples = [_fixture("2025-09-01"), _fixture("2025-09-02")]
    with pytest.raises(ValueError, match="held-out"):
        audit_training_only_nonbinding_masks(
            samples + [_fixture("2025-09-03")],
            holdout_start_date="2025-09-03",
        )
    with pytest.raises(ValueError, match="held-out"):
        audit_training_only_nonbinding_masks(
            samples, holdout_start_date="2025-09-02",
        )
    with pytest.raises(ValueError, match="Duplicate"):
        audit_training_only_nonbinding_masks(
            [samples[0], samples[0]], holdout_start_date="2025-09-03",
        )


def test_training_evidence_rejects_topology_drift_and_untrusted_snapshots():
    sample = _fixture("2025-09-01")
    different = _fixture("2025-09-02")
    different["dcNetwork"]["lines"][0]["limitMw"] = 999
    with pytest.raises(ValueError, match="topology"):
        audit_training_only_nonbinding_masks(
            [sample, different], holdout_start_date="2025-09-03",
        )
    different = _fixture("2025-09-02")
    different["historicalBacktestOnly"] = False
    with pytest.raises(ValueError, match="historical"):
        audit_training_only_nonbinding_masks(
            [sample, different], holdout_start_date="2025-09-03",
        )
