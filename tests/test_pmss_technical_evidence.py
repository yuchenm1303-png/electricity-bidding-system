"""Private generator model observations never confer physical UC readiness."""
import json
from pathlib import Path

import pytest

from powerbid.pmss_integration import snapshot_from_pmss
from powerbid.pmss_technical_evidence import (
    sanitize_pmss_technical_evidence,
    validate_client_technical_evidence,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "data/examples/synthetic_dc_pmss.json"


def model():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    units = [{
        "id": spec.unit_id,
        "minCapacity": spec.min_power_mw,
        "pdAdjustMax": spec.capacity_mw,
        "minOnTime": 0,
        "minOffTime": 0,
        "incRate": 20.0,
        "decRate": 20.0,
        "launchCost": 0.0,
        "cookie": "MUST_NEVER_LEAVE_TRUSTED_HOST",
    } for spec in snapshot.units]
    return snapshot, {"units": {"datas": units}}


def test_technical_evidence_strips_unknown_private_fields_and_preserves_uncertainty():
    snapshot, private = model()
    exported = sanitize_pmss_technical_evidence(private, snapshot=snapshot)
    assert exported["unitCount"] == 2
    assert exported["capacityMatched"] == 2
    assert exported["minimumMatched"] == 2
    assert exported["jointMilpReady"] is False
    assert exported["technicalInputsVerified"] is False
    assert exported["observedFields"]["incRate"]["min"] == 20
    assert exported["observedFields"]["incRate"]["distinct"] == 1
    assert exported["observedFields"]["minOnTime"]["zero"] == 2
    assert exported["observedFields"]["launchCost"]["zero"] == 2
    assert "MUST_NEVER_LEAVE_TRUSTED_HOST" not in json.dumps(exported)
    public = validate_client_technical_evidence(exported, snapshot=snapshot)
    assert public["joint_milp_ready"] is False
    assert public["source_claim_only"] is True


def test_reject_wrong_unit_ids_capacity_mismatch_and_poisoned_numbers():
    snapshot, private = model()
    private["units"]["datas"][0]["id"] = "unknown"
    with pytest.raises(ValueError, match="IDs"):
        sanitize_pmss_technical_evidence(private, snapshot=snapshot)
    snapshot, private = model()
    private["units"]["datas"][0]["pdAdjustMax"] += 1
    with pytest.raises(ValueError, match="bounds"):
        sanitize_pmss_technical_evidence(private, snapshot=snapshot)
    snapshot, private = model()
    private["units"]["datas"][0]["incRate"] = float("nan")
    with pytest.raises(ValueError, match="nonnegative finite"):
        sanitize_pmss_technical_evidence(private, snapshot=snapshot)
    snapshot, private = model()
    private["units"]["datas"][0]["minOnTime"] = False
    with pytest.raises(ValueError, match="nonnegative finite"):
        sanitize_pmss_technical_evidence(private, snapshot=snapshot)


def test_client_cannot_claim_verified_technical_parameters():
    snapshot, grid = model()
    audit = sanitize_pmss_technical_evidence(grid, snapshot=snapshot)
    audit["jointMilpReady"] = True
    with pytest.raises(ValueError, match="cannot claim"):
        validate_client_technical_evidence(audit, snapshot=snapshot)
    audit["jointMilpReady"] = False
    audit["observedFields"]["incRate"]["validated_for_joint_milp"] = True
    with pytest.raises(ValueError, match="verified"):
        validate_client_technical_evidence(audit, snapshot=snapshot)


def test_client_rejects_inconsistent_and_missing_statistics():
    snapshot, grid = model()
    audit = sanitize_pmss_technical_evidence(grid, snapshot=snapshot)
    audit["observedFields"]["incRate"]["zero"] = 2
    with pytest.raises(ValueError, match="Inconsistent"):
        validate_client_technical_evidence(audit, snapshot=snapshot)
    audit = sanitize_pmss_technical_evidence(grid, snapshot=snapshot)
    audit["observedFields"].pop("launchCost")
    with pytest.raises(ValueError, match="Incomplete"):
        validate_client_technical_evidence(audit, snapshot=snapshot)
