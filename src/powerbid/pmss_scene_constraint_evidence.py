"""Credential-free counts from read-only PMSS scenario calculation constraints.

Backed by two routes confirmed in the teacher JavaScript source:
POST scene/unitParam/list and GET project/getUnitInitialStateInput.
Neither row identifiers nor arbitrary source fields are exported.
Raw flags are NOT mapped to ThermalConstraints, and no model is unlocked.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

SWITCHES = (
    "ifConRamp", "ifConEnergy", "ifConInitPower",
    "ifConUpDnTimes", "ifConMinOnOffTm",
    "ifConStartCost", "ifConNoloadCost",
)
INITIAL_FIELDS = (
    "initialState", "keepTime", "power",
    "downStatus", "minOnTime", "minOffTime",
)


def _rows(page: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(page, Mapping):
        raise ValueError(f"{label}: expected read-only paginated response")
    data = page.get("datas")
    if not isinstance(data, list) or len(data) > 999 or not all(
        isinstance(x, dict) for x in data
    ):
        raise ValueError(f"{label}: invalid PMSS table rows")
    count = page.get("rowCount")
    if type(count) is not int or count != len(data):
        raise ValueError(
            f"{label}: expected all rows in one page; pagination incomplete"
        )
    return data


def _switch(raw: Any) -> str:
    # A numerical 1/0 is not automatically a verified enable/disable.
    # The PMSS backend may use inverse or tri-state flags. Report the
    # exact binary *code*, never its physical effect.
    if raw is True or raw == 1 or raw == "1":
        return "value_1"
    if raw is False or raw == 0 or raw == "0":
        return "value_0"
    if raw is None or raw == "":
        return "missing"
    return "unrecognized"


def _numeric(raw: Any) -> float | None:
    if type(raw) not in (int, float) or not isfinite(raw):
        return None
    return float(raw)


def summarize_scene_constraint_evidence(
    calculate_page: Any,
    initial_page: Any,
    *,
    expected_units: int,
) -> dict[str, Any]:
    if type(expected_units) is not int or not 1 <= expected_units <= 30:
        raise ValueError("Expected unit count outside approved research range")
    calc = _rows(calculate_page, "calculation constraints")
    initial = _rows(initial_page, "initial state")
    flags: dict[str, dict[str, int]] = {}
    for field in SWITCHES:
        counts = {"value_1": 0, "value_0": 0, "missing": 0, "unrecognized": 0}
        for record in calc:
            counts[_switch(record.get(field))] += 1
        flags[field] = counts
    fields: dict[str, dict[str, Any]] = {}
    for field in INITIAL_FIELDS:
        values = [item.get(field) for item in initial]
        numeric = [_numeric(v) for v in values]
        known = [v for v in numeric if v is not None]
        fields[field] = {
            "present": sum(v is not None for v in values),
            "numeric": len(known),
            "minimum": min(known) if known else None,
            "maximum": max(known) if known else None,
            "unitsVerified": False,
        }
    return {
        "source": "Authorized read-only PMSS scene/unitParam/list and "
                  "project/getUnitInitialStateInput queries",
        "expectedUnits": expected_units,
        "constraintRows": len(calc),
        "initialRows": len(initial),
        "switches": flags,
        "initialFields": fields,
        "sourceClaimOnly": True,
        "physicalUnitsVerified": False,
        "jointMilpReady": False,
        "remark": (
            "Value_1/value_0 are unverified encoded codes, NOT proven on/off states. "
            "Counts describe a particular source scene and case only. "
            "No case-to-bid unit identity mapping, model flag semantics, "
            "initial-state encoding, or ramp/time unit validation is implied."
        ),
    }


def validate_scene_constraint_evidence(
    raw: Any,
    *,
    expected_units: int,
) -> dict[str, Any]:
    """Fail closed on any fabricated readiness or modified field schema."""
    if not isinstance(raw, dict) or set(raw) != {
        "source", "expectedUnits", "constraintRows", "initialRows",
        "switches", "initialFields", "sourceClaimOnly",
        "physicalUnitsVerified", "jointMilpReady", "remark",
    }:
        raise ValueError("Invalid PMSS scene-constraint evidence structure")
    if type(raw["expectedUnits"]) is not int or raw["expectedUnits"] != expected_units:
        raise ValueError("PMSS constraint evidence target generator count differs")
    if any(type(raw[k]) is not int or not 0 <= raw[k] <= 999 for k in (
        "constraintRows", "initialRows",
    )):
        raise ValueError("Invalid read-only PMSS result counts")
    if not (
        raw["sourceClaimOnly"] is True
        and raw["physicalUnitsVerified"] is False
        and raw["jointMilpReady"] is False
    ):
        raise ValueError("PMSS observations cannot assert verified physical constraints")
    if raw["source"] != (
        "Authorized read-only PMSS scene/unitParam/list and "
        "project/getUnitInitialStateInput queries"
    ):
        raise ValueError("Unexpected scene constraint source")
    if not isinstance(raw["remark"], str) or len(raw["remark"]) > 500:
        raise ValueError("Invalid scene-constraint disclaimer")
    if not isinstance(raw["switches"], dict) or set(raw["switches"]) != set(SWITCHES):
        raise ValueError("Unknown or missing PMSS switch name")
    for field in SWITCHES:
        stat = raw["switches"][field]
        if not isinstance(stat, dict) or set(stat) != {
            "value_1", "value_0", "missing", "unrecognized",
        } or any(type(v) is not int or v < 0 for v in stat.values()):
            raise ValueError("Invalid PMSS constraint-switch statistics")
        if sum(stat.values()) != raw["constraintRows"]:
            raise ValueError("PMSS flag coverage differs from retrieved rows")
    if not isinstance(raw["initialFields"], dict) or set(raw["initialFields"]) != set(
        INITIAL_FIELDS
    ):
        raise ValueError("Invalid PMSS initial-state fields")
    for field in INITIAL_FIELDS:
        stat = raw["initialFields"][field]
        if not isinstance(stat, dict) or set(stat) != {
            "present", "numeric", "minimum", "maximum", "unitsVerified",
        }:
            raise ValueError("Invalid PMSS initial-state field statistics")
        if stat["unitsVerified"] is not False:
            raise ValueError("Initial-state physical units not independently established")
        p, n = stat["present"], stat["numeric"]
        if type(p) is not int or type(n) is not int or not 0 <= n <= p <= raw["initialRows"]:
            raise ValueError("PMSS initial-field coverage inconsistent")
        lower, upper = stat["minimum"], stat["maximum"]
        if n:
            if _numeric(lower) is None or _numeric(upper) is None or lower > upper:
                raise ValueError("PMSS initial-field numeric ranges inconsistent")
        elif lower is not None or upper is not None:
            raise ValueError("Empty initial-field ranges require null")
    return {
        "expected_units": expected_units,
        "constraint_rows": raw["constraintRows"],
        "initial_rows": raw["initialRows"],
        "switches": raw["switches"],
        "initial_fields": raw["initialFields"],
        "physical_units_verified": False,
        "joint_milp_ready": False,
        "note": "Read-only scene flags, not certified generator UC constraints",
    }
