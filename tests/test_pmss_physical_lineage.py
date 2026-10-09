"""Course-cited UC data must be an exact, field-by-field, case-bound claim."""
from __future__ import annotations

from copy import deepcopy

import pytest
from test_pmss_joint_mwh_range_api import _payload

from powerbid.pmss_integration import snapshot_from_pmss
from powerbid.pmss_physical_lineage import (
    FIELD_UNITS,
    draft_lineage_template,
    validate_technical_lineage,
)


def _example():
    payload = _payload()
    raw = payload["snapshot"]
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    technical = payload["technical"]
    template = draft_lineage_template(
        snapshot, technical, case_date=raw["caseDate"]
    )
    return snapshot, technical, template


def _filled(raw):
    document = deepcopy(raw)
    for uid, fields in document["units"].items():
        for field, item in fields.items():
            item["reference"] = f"course handout section {uid} page 12 - {field}"
    return document


def test_template_has_zero_guessed_references_and_all_13_fields():
    snapshot, technical, blank = _example()
    assert blank["case_date"] == "2025-09-01"
    assert set(blank["units"]) == {"G30", "G31"}
    assert all(set(item) == set(FIELD_UNITS) for item in blank["units"].values())
    assert blank["units"]["G30"]["initial_on"]["value"] is True
    assert blank["units"]["G30"]["initial_on"]["unit"] == "boolean"
    assert blank["units"]["G30"]["ramp_up_mw"]["unit"] == "MW/h"
    assert blank["units"]["G30"]["startup_ramp_mw"]["unit"] == "MW/transition"
    assert all(not line["reference"] for u in blank["units"].values()
               for line in u.values())
    with pytest.raises(ValueError, match="source reference required"):
        validate_technical_lineage(
            snapshot, technical, blank, case_date="2025-09-01"
        )


def test_all_fields_matched_claim_is_research_only_not_independent_verification():
    snapshot, technical, blank = _example()
    report = validate_technical_lineage(
        snapshot, technical, _filled(blank), case_date="2025-09-01"
    )
    assert report.attested_fields == 26
    assert report.total_required_fields == 26
    assert report.unit_count == 2
    assert report.values_match_computation_file
    assert report.user_source_attested
    assert report.independent_pmss_semantics_verified is False
    assert report.usable_only_for_local_research is True


@pytest.mark.parametrize(("field", "mutated", "expected"), [
    ("initial_on", 1, "value differs"),
    ("ramp_up_mw", "100", "value differs"),
    ("max_mw", 999, "value differs"),
    ("startup_cost", float("nan"), "value differs"),
    ("min_up_hours", 1.0, "value differs"),
])
def test_lineage_value_changes_block_execution(field, mutated, expected):
    snapshot, technical, blank = _example()
    manifest = _filled(blank)
    manifest["units"]["G30"][field]["value"] = mutated
    with pytest.raises(ValueError, match=expected):
        validate_technical_lineage(
            snapshot, technical, manifest, case_date="2025-09-01"
        )


@pytest.mark.parametrize(("field", "wrong_unit"), [
    ("ramp_up_mw", "MW/min"),
    ("initial_state_hours", "seconds"),
    ("startup_ramp_mw", "MW/h"),
    ("startup_cost", "USD"),
])
def test_wrong_physical_units_are_rejected_without_implicit_conversion(
    field, wrong_unit,
):
    snapshot, technical, blank = _example()
    manifest = _filled(blank)
    manifest["units"]["G30"][field]["unit"] = wrong_unit
    with pytest.raises(ValueError, match="unit must be"):
        validate_technical_lineage(
            snapshot, technical, manifest, case_date="2025-09-01"
        )


def test_wrong_day_missing_unit_extra_field_unknown_source_and_secret_blocked():
    snapshot, technical, blank = _example()
    manifest = _filled(blank)
    manifest["case_date"] = "2025-09-02"
    with pytest.raises(ValueError, match="date differs"):
        validate_technical_lineage(
            snapshot, technical, manifest, case_date="2025-09-01"
        )
    manifest = _filled(blank)
    del manifest["units"]["G30"]["initial_mw"]
    with pytest.raises(ValueError, match="every physical field"):
        validate_technical_lineage(
            snapshot, technical, manifest, case_date="2025-09-01"
        )
    manifest = _filled(blank)
    manifest["units"]["OTHER"] = manifest["units"].pop("G31")
    with pytest.raises(ValueError, match="unit IDs"):
        validate_technical_lineage(
            snapshot, technical, manifest, case_date="2025-09-01"
        )
    manifest = _filled(blank)
    manifest["source_kind"] = "extracted_pmss_flags"
    with pytest.raises(ValueError, match="user-attested"):
        validate_technical_lineage(
            snapshot, technical, manifest, case_date="2025-09-01"
        )
    manifest = _filled(blank)
    manifest["units"]["G30"]["initial_on"]["reference"] = (
        "https://example.org/handout?token=do_not_upload"
    )
    with pytest.raises(ValueError, match="secrets and URLs"):
        validate_technical_lineage(
            snapshot, technical, manifest, case_date="2025-09-01"
        )


def test_mutated_model_technical_values_require_new_matching_lineage():
    snapshot, technical, blank = _example()
    modified = deepcopy(technical)
    modified["G30"]["ramp_down_mw"] = 50
    with pytest.raises(ValueError, match="value differs"):
        validate_technical_lineage(
            snapshot, modified, _filled(blank), case_date="2025-09-01"
        )
