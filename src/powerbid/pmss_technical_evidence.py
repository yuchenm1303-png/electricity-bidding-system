"""Read-only PMSS generator-parameter evidence, NOT validated UC inputs.

The original PMSS power-model units table contains field names that resemble
thermal constraints. In this dataset several values are zero or a uniform 20.
Neither raw names nor numeric values establish units, meaning, equipment
applicability, or valid initial-state/transition assumptions.

This is an allowlisted, credential-free summary. Do not promote ANY observed
field into ThermalConstraints without separately verified semantics.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

from powerbid.pmss_integration import PMSSSnapshot

OBSERVED_FIELDS = (
    "minCapacity", "pdAdjustMax", "minOnTime", "minOffTime",
    "incRate", "decRate", "launchCost",
)
NEEDS_UNIT_VERIFICATION = {
    "minCapacity": "model lower MW limit; not necessarily technical Pmin",
    "pdAdjustMax": "declared adjustable MW limit; not necessarily physical Pmax",
    "minOnTime": "units and meaning of zero not established",
    "minOffTime": "units and meaning of zero not established",
    "incRate": "MW per hour vs other time base unknown",
    "decRate": "MW per hour vs other time base unknown",
    "launchCost": "cost components and currency/zero semantics unknown",
}


def _number(value: Any, label: str) -> float:
    if type(value) not in (float, int) or not isfinite(value) or value < 0:
        raise ValueError(f"{label} must be a nonnegative finite PMSS model value")
    return float(value)


def sanitize_pmss_technical_evidence(
    private_grid: Mapping[str, Any], *, snapshot: PMSSSnapshot,
) -> dict[str, Any]:
    """Exact-join all real units, then return only numeric aggregate evidence."""
    if not isinstance(private_grid, Mapping):
        raise ValueError("Expected authorized read-only PMSS grid")
    try:
        rows = private_grid["units"]["datas"]
    except (TypeError, KeyError) as exc:
        raise ValueError("Missing PMSS private generation table") from exc
    if not isinstance(rows, list) or len(rows) != len(snapshot.units):
        raise ValueError("PMSS generation count differs from sanitized snapshot")
    identified = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("Generator lacks stable internal ID")
        ident = row["id"]
        if not ident or ident in identified:
            raise ValueError("Missing/duplicate PMSS generator ID")
        identified[ident] = row
    expected = {u.unit_id: u for u in snapshot.units}
    if set(identified) != set(expected):
        raise ValueError("Original PMSS generator IDs differ from bidding snapshot")

    columns: dict[str, dict[str, Any]] = {}
    observed: dict[str, dict[str, float]] = {uid: {} for uid in expected}
    for field in OBSERVED_FIELDS:
        values = []
        for uid in expected:
            raw = identified[uid].get(field)
            if raw is None:
                continue
            n = _number(raw, field)
            observed[uid][field] = n
            values.append(n)
        columns[field] = {
            "present": len(values),
            "zero": sum(x == 0 for x in values),
            "distinct": len(set(values)),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "meaning": NEEDS_UNIT_VERIFICATION[field],
            "validated_for_joint_milp": False,
        }

    matched_capacity = 0
    matched_minimum = 0
    for uid, unit in expected.items():
        upper = observed[uid].get("pdAdjustMax")
        lower = observed[uid].get("minCapacity")
        if upper is not None and abs(upper - unit.capacity_mw) <= 1e-6:
            matched_capacity += 1
        if lower is not None and abs(lower - unit.min_power_mw) <= 1e-6:
            matched_minimum += 1
    if matched_capacity != len(expected) or matched_minimum != len(expected):
        raise ValueError("Original grid output bounds disagree with sanitized unit tree")

    return {
        "source": "PMSS power-model units table; unverified field semantics",
        "unitCount": len(expected),
        "capacityMatched": matched_capacity,
        "minimumMatched": matched_minimum,
        "observedFields": columns,
        "sourceClaimOnly": True,
        "technicalInputsVerified": False,
        "jointMilpReady": False,
        "remark": (
            "Observed numbers are NOT sufficient for 24h UC; initial on/off "
            "state, initial MW/state duration, transition ramps, shutdown cost "
            "and valid field unit interpretation remain unsupported."
        ),
    }


def validate_client_technical_evidence(
    raw: Any, *, snapshot: PMSSSnapshot,
) -> dict[str, Any]:
    """Validate uploaded observation summary shape; NEVER certify provenance."""
    if not isinstance(raw, dict) or set(raw) != {
        "source", "unitCount", "capacityMatched", "minimumMatched",
        "observedFields", "sourceClaimOnly", "technicalInputsVerified",
        "jointMilpReady", "remark",
    }:
        raise ValueError("Malformed PMSS technical evidence")
    count = len(snapshot.units)
    if any(type(raw[k]) is not int or raw[k] != count for k in (
        "unitCount", "capacityMatched", "minimumMatched",
    )):
        raise ValueError("PMSS technical evidence generator coverage mismatch")
    if (raw["sourceClaimOnly"] is not True or
        raw["technicalInputsVerified"] is not False or
        raw["jointMilpReady"] is not False):
        raise ValueError("Uploaded PMSS observations cannot claim verified UC status")
    if not isinstance(raw["source"], str) or len(raw["source"]) > 200:
        raise ValueError("Invalid PMSS technical observation source")
    if not isinstance(raw["remark"], str) or len(raw["remark"]) > 600:
        raise ValueError("Invalid PMSS technical observation disclaimer")
    stats = raw["observedFields"]
    if not isinstance(stats, dict) or set(stats) != set(OBSERVED_FIELDS):
        raise ValueError("Incomplete technical source fields")
    expected_keys = {
        "present", "zero", "distinct", "min", "max",
        "meaning", "validated_for_joint_milp",
    }
    for field, row in stats.items():
        if not isinstance(row, dict) or set(row) != expected_keys:
            raise ValueError("Malformed technical field statistics")
        present, zero, distinct = (row[k] for k in ("present", "zero", "distinct"))
        if any(type(v) is not int for v in (present, zero, distinct)):
            raise ValueError("Technical statistics counts must be integers")
        if not 0 <= zero <= present <= count or not 0 <= distinct <= present:
            raise ValueError("Invalid technical field coverage")
        if row["meaning"] != NEEDS_UNIT_VERIFICATION[field]:
            raise ValueError("Technical field meaning must not be relabeled")
        if row["validated_for_joint_milp"] is not False:
            raise ValueError("Unknown physical field must not be declared verified")
        if present:
            lo = _number(row["min"], field)
            hi = _number(row["max"], field)
            if lo > hi or (zero and lo != 0) or (
                distinct == 1 and lo != hi
            ):
                raise ValueError("Inconsistent technical field statistics")
        elif any(row[k] is not None for k in ("min", "max")):
            raise ValueError("Absent field must have null bounds")
    return {
        "unit_count": count,
        "capacity_match_count": count,
        "minimum_match_count": count,
        "source_claim_only": True,
        "technical_inputs_verified": False,
        "joint_milp_ready": False,
        "observed_fields": stats,
        "note": "Client-provided read-only data summary; field units not verified",
    }
