"""Field-level, case-bound provenance for USER-ATTESTED DC+UC parameters.

This is a *documentation and integrity gate*, NOT an independently
verified PMSS data pipeline. A valid citation is an assertion supplied by
the user, not proof that the teacher's actual simulator uses these units.
PMSS scene flags and anonymous aggregate evidence cannot satisfy it.

For course-labelled technical inputs, EVERY machine and EVERY numerical or
Boolean ThermalConstraints field must be bound to a source reference, with
the declared value and exact physical unit. No guessed default, implicit
conversion, historical accepted MW, or value-from-unverified-flag is allowed.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any

from powerbid.pmss_integration import PMSSSnapshot
from powerbid.pmss_joint_research import FIELDS, _spec, assess_joint_readiness

FIELD_UNITS = {
    "min_mw": "MW",
    "max_mw": "MW",
    "ramp_up_mw": "MW/h",
    "ramp_down_mw": "MW/h",
    "startup_ramp_mw": "MW/transition",
    "shutdown_ramp_mw": "MW/transition",
    "min_up_hours": "h",
    "min_down_hours": "h",
    "startup_cost": "bid-cost/start",
    "shutdown_cost": "bid-cost/stop",
    "initial_on": "boolean",
    "initial_mw": "MW",
    "initial_state_hours": "h",
}
if set(FIELD_UNITS) != FIELDS - {"unit_id"}:
    raise RuntimeError("UC lineage field units do not cover all physical model inputs")


@dataclass(frozen=True, slots=True)
class PhysicalLineageAudit:
    case_date: str
    unit_count: int
    attested_fields: int
    total_required_fields: int
    source_kind: str
    values_match_computation_file: bool
    user_source_attested: bool
    independent_pmss_semantics_verified: bool = False
    usable_only_for_local_research: bool = True
    disclaimer: str = (
        "Uploaded value/unit/source references are USER ASSERTIONS. "
        "No independent verification of teacher PMSS initial-state codes, "
        "field units, constraint switches, or actual SCUC costs is implied."
    )


def draft_lineage_template(
    snapshot: PMSSSnapshot,
    records: Mapping[str, Any],
    *,
    case_date: str,
) -> dict[str, Any]:
    """Populate matching values/units; NEVER fabricate any field references.

    The resulting blank-reference template is intentionally NOT runnable as
    a provenanced research input until every reference is filled by a person
    using actual unit-specific course or equipment documents.
    """
    _case_date(case_date)
    readiness = assess_joint_readiness(snapshot, records, source="course_verified_by_user")
    if not readiness.ready:
        raise ValueError("Technical records must be complete before creating a lineage template")
    return {
        "schema_version": 1,
        "case_date": case_date,
        "source_kind": "course_manual_user_attestation",
        "units": {
            uid: {
                field: {
                    "value": records[uid][field],
                    "unit": unit,
                    "reference": "",
                }
                for field, unit in FIELD_UNITS.items()
            }
            for uid in sorted(records)
        },
    }


def _case_date(raw: Any) -> str:
    if type(raw) is not str or len(raw) != 10:
        raise ValueError("Lineage case_date must be YYYY-MM-DD")
    try:
        if date.fromisoformat(raw).isoformat() != raw:
            raise ValueError("Invalid ISO date")
    except (TypeError, ValueError) as exc:
        raise ValueError("Lineage case_date must be YYYY-MM-DD") from exc
    return raw


def _source_reference(text: Any, *, unit: str, field: str) -> str:
    if type(text) is not str or not 8 <= len(text.strip()) <= 220:
        raise ValueError(f"{unit}.{field}: explicit 8..220-character source reference required")
    normalized = text.lower().replace(" ", "")
    # No credentials, query parameters, cookies, or URLs in the audit
    # manifest. Use handbook title, section/page and date instead.
    if any(keyword in normalized for keyword in (
        "https://", "http://", "cookie", "token", "password",
        "secret", "bearer", "session", "authorization", "?",
    )):
        raise ValueError(f"{unit}.{field}: secrets and URLs are not valid source references")
    return text.strip()


def validate_technical_lineage(
    snapshot: PMSSSnapshot,
    records: Mapping[str, Any],
    raw: Any,
    *,
    case_date: str,
) -> PhysicalLineageAudit:
    """Fail closed if field values, physical units, identity or date differ.

    Numerical and Boolean values use strict input types. Matching document
    references is evidence bookkeeping, not document authenticity checking.
    """
    case_date = _case_date(case_date)
    if not isinstance(raw, Mapping) or set(raw) != {
        "schema_version", "case_date", "source_kind", "units",
    }:
        raise ValueError("Lineage manifest must have the exact approved root schema")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("Unsupported lineage manifest schema version")
    if raw["case_date"] != case_date:
        raise ValueError("Lineage case date differs from PMSS research snapshot")
    if raw["source_kind"] != "course_manual_user_attestation":
        raise ValueError("Lineage must be explicitly user-attested course evidence")
    source_units = raw["units"]
    if not isinstance(source_units, Mapping):
        raise ValueError("Lineage units must be an object")
    expected = {unit.unit_id for unit in snapshot.units}
    if set(source_units) != expected or set(records) != expected:
        raise ValueError("Lineage must cover exactly the same PMSS and technical unit IDs")
    readiness = assess_joint_readiness(snapshot, records, source="course_verified_by_user")
    if not readiness.ready:
        raise ValueError("Technical records are incomplete or inconsistent with PMSS snapshot")

    for uid in sorted(expected):
        # Prevent bypass via direct function use or unknown extra numeric
        # keys without first passing exact schema/range checking.
        _spec(uid, records[uid])
        document = source_units[uid]
        if not isinstance(document, Mapping) or set(document) != set(FIELD_UNITS):
            raise ValueError(f"{uid}: every physical field needs its own evidence entry")
        for field, required_unit in FIELD_UNITS.items():
            entry = document[field]
            if not isinstance(entry, Mapping) or set(entry) != {
                "value", "unit", "reference",
            }:
                raise ValueError(f"{uid}.{field}: malformed value/unit/reference entry")
            if entry["unit"] != required_unit:
                raise ValueError(
                    f"{uid}.{field}: unit must be explicitly {required_unit}; "
                    "implicit time/cost conversion prohibited"
                )
            declared = entry["value"]
            original = records[uid][field]
            if field == "initial_on":
                match = type(declared) is bool and declared is original
            elif field in ("min_up_hours", "min_down_hours", "initial_state_hours"):
                match = type(declared) is int and declared == original
            else:
                match = (
                    type(declared) in (int, float) and isfinite(declared)
                    and abs(float(declared) - float(original)) <= 1e-10
                )
            if not match:
                raise ValueError(
                    f"{uid}.{field}: evidence value differs from actual model parameter"
                )
            _source_reference(entry["reference"], unit=uid, field=field)
    return PhysicalLineageAudit(
        case_date=case_date,
        unit_count=len(expected),
        attested_fields=len(expected) * len(FIELD_UNITS),
        total_required_fields=len(expected) * len(FIELD_UNITS),
        source_kind="course_manual_user_attestation",
        values_match_computation_file=True,
        user_source_attested=True,
    )
