"""Case-bound PMSS standard import using existing read-only parsers only.

Outputs are PRIVATE historical research artifacts. This module performs no
network requests itself and cannot write bids or trigger PMSS clearing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from math import isfinite
from typing import Any

from powerbid.adapters.teacher_platform import TeacherPlatformAdapter, TeacherPlatformContext
from powerbid.pmss_export import build_da_scene_snapshot
from powerbid.pmss_grid_bridge import sanitize_pmss_network
from powerbid.pmss_integration import (
    curve_for_period,
    parse_unit_clearing,
    snapshot_from_pmss,
)
from powerbid.pmss_physical_lineage import FIELD_UNITS
from powerbid.pmss_results import parse_branch_flows, parse_nodal_prices
from powerbid.pmss_scene_constraint_evidence import (
    summarize_scene_constraint_evidence,
    validate_scene_constraint_evidence,
)

SCHEMA_VERSION = "powerbid.pmss.standard.v1"
DEFAULT_COUNTS = (39, 46, 10)
SERIES_FIELDS = {
    "unitResults": ("accepted_mw", "clearing_prices", "income"),
    "nodalPrices": ("lmp",),
    "branchFlows": (
        "flow_mw",
        "from_node_price",
        "to_node_price",
        "shadow_price",
        "congestion_surplus",
    ),
}


def _case_date(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("A case-bound YYYY-MM-DD date is required")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Invalid case date")
    except ValueError as exc:
        raise ValueError("A valid case-bound YYYY-MM-DD date is required") from exc
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} is not a finite number")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label} is not a finite number") from exc
    if not isfinite(result):
        raise ValueError(f"{label} is not a finite number")
    return result


def _series(raw: Any, label: str, *, nonnegative: bool = False) -> list[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 24:
        raise ValueError(f"{label}: expected 24 hourly values")
    values = [_number(v, label) for v in raw]
    if nonnegative and any(v < 0 for v in values):
        raise ValueError(f"{label}: negative MW is unsupported")
    return values


def _historical(
    raw: Any,
    *,
    unit_names: dict[str, str],
    bus_ids: set[str],
    branch_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or raw.get("marketTypeAtom") != "DA":
        raise ValueError("Expected day-ahead historical clearing results")
    if type(raw.get("periodNum")) is not int or raw["periodNum"] != 24:
        raise ValueError("Historical clearing must cover 24 periods")
    # Early server-side exports contain confirmed native PMSS rows, while
    # current read_market_results already emits normalized dataclasses.
    # Reuse the established parsers for both formats.
    if all(
        isinstance(raw.get(name), list)
        and raw[name]
        and isinstance(raw[name][0], Mapping)
        and "elementId" in raw[name][0]
        for name in SERIES_FIELDS
    ):
        raw = {
            "marketTypeAtom": "DA",
            "periodNum": 24,
            "unitResults": [
                asdict(row)
                for row in parse_unit_clearing({"periodNum": 24, "datas": raw["unitResults"]})
            ],
            "nodalPrices": [
                asdict(row)
                for row in parse_nodal_prices({"period": 24, "data": raw["nodalPrices"]})
            ],
            "branchFlows": [
                asdict(row)
                for row in parse_branch_flows({"period": 24, "data": raw["branchFlows"]})
            ],
        }
    identifiers = {
        "unitResults": set(unit_names),
        "nodalPrices": bus_ids,
        "branchFlows": branch_ids,
    }
    result: dict[str, Any] = {"marketTypeAtom": "DA", "periodNum": 24}
    for section, expected in identifiers.items():
        rows = raw.get(section)
        if not isinstance(rows, list) or len(rows) != len(expected):
            raise ValueError(f"{section}: incomplete historical result coverage")
        key = "unit_id" if section == "unitResults" else "element_id"
        selected: set[str] = set()
        safe_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError(f"{section}: invalid result record")
            ident = row.get(key)
            if not isinstance(ident, str) or ident not in expected or ident in selected:
                raise ValueError(f"{section}: duplicate or unrelated element ID")
            selected.add(ident)
            if row.get("market_type") != "DA":
                raise ValueError(f"{section}: result market type mismatch")
            sanitized = {
                key: ident,
                "name": unit_names[ident] if section == "unitResults" else ident,
                "market_type": "DA",
            }
            for field in SERIES_FIELDS[section]:
                sanitized[field] = _series(
                    row.get(field),
                    f"{section}.{field}",
                    nonnegative=field == "accepted_mw",
                )
            safe_rows.append(sanitized)
        if selected != expected:
            raise ValueError(f"{section}: result identity coverage mismatch")
        result[section] = safe_rows
    return result


def build_standard_pmss_model(
    source_snapshot: Mapping[str, Any],
    private_grid: Mapping[str, Any],
    *,
    grid_case_date: str,
    expected_counts: tuple[int, int, int] = DEFAULT_COUNTS,
    scene_constraint_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and allowlist a complete DA case without copying source secrets.

    The PMSS grid export does not carry a trusted case-date binding; require
    the operator to assert its date and reject mismatched historical scenes.
    """
    if not isinstance(source_snapshot, Mapping):
        raise ValueError("PMSS case snapshot must be an object")
    case_date = _case_date(source_snapshot.get("caseDate"))
    if _case_date(grid_case_date) != case_date:
        raise ValueError("Grid case date must match the historical scene case")
    if (
        not isinstance(expected_counts, tuple)
        or len(expected_counts) != 3
        or any(type(n) is not int or n < 1 for n in expected_counts)
    ):
        raise ValueError("Expected topology counts must be positive integers")
    if source_snapshot.get("loadSourceKind") != "PMSS_DA_SCENE_LOAD_INPUT":
        raise ValueError("DA demand must come from a historical PMSS scene load input")
    if source_snapshot.get("historicalBacktestOnly") is not True:
        raise ValueError("Historical PMSS demand is not a forward prediction")
    source_tree = source_snapshot.get("unitTree")
    source_bids = source_snapshot.get("unitBids")
    source_rules = source_snapshot.get("marketSystem")
    if not isinstance(source_tree, list) or not isinstance(source_bids, Mapping):
        raise ValueError("Missing PMSS unit tree or historical bidding data")
    if not isinstance(source_rules, Mapping):
        raise ValueError("Missing PMSS market rules")
    demand = _series(
        source_snapshot.get("demandForecastMw"), "historical scene load", nonnegative=True
    )
    # Never copy user-controlled source labels or unexpected source attributes.
    label = "PMSS day-ahead operating-scene input (historical, not predictive)"
    snapshot = snapshot_from_pmss(
        unit_tree=source_tree,
        unit_bids=source_bids,
        market_system=source_rules,
        demand_forecast_mw=demand,
        forecast_source=label,
    )
    network = sanitize_pmss_network(private_grid, snapshot=snapshot)
    buses, branches, unit_bus = network["buses"], network["lines"], network["unitBus"]
    counts = (len(buses), len(branches), len(snapshot.units))
    if counts != expected_counts:
        raise ValueError(
            f"PMSS topology counts incomplete: expected {expected_counts}, got {counts}"
        )
    unit_names = {unit.unit_id: unit.name for unit in snapshot.units}
    if set(unit_bus) != set(unit_names):
        raise ValueError("Network generators do not match bidding generator IDs")
    if source_snapshot.get("loadNodeCount") not in (None, len(buses)):
        raise ValueError("DA scene load node count differs from grid topology")
    totals = [0.0] * 24
    for bus in buses:
        row = _series(network["hourlyDemandMw"].get(bus), "bus demand", nonnegative=True)
        for i, value in enumerate(row):
            totals[i] += value
    if any(abs(a - b) > 0.1 for a, b in zip(totals, demand, strict=True)):
        raise ValueError("PMSS demand and grid nodal load refer to different cases")
    branch_ids = {line["lineId"] for line in branches}
    if len(branch_ids) != len(branches):
        raise ValueError("Duplicate branch identities")
    results = _historical(
        source_snapshot.get("results"),
        unit_names=unit_names,
        bus_ids=set(buses),
        branch_ids=branch_ids,
    )
    safe_units = [
        {
            "unitId": unit.unit_id,
            "key": unit.unit_id,
            "title": unit.name,
            "leaf": True,
            "pdAdjustMax": unit.capacity_mw,
            "pdAdjustMin": unit.min_power_mw,
            "runningCost": unit.running_cost,
            "unitType": unit.unit_type,
        }
        for unit in snapshot.units
    ]
    safe_bids: dict[str, dict[str, Any]] = {}
    historical_price_rule_warnings = 0
    for unit in snapshot.units:
        bid = source_bids[unit.unit_id]
        costs = {}
        for key in ("minTechPowerCost", "startCostHot", "startCostWarm", "startCostCold"):
            if key in bid:
                costs[key] = _number(bid[key], f"{key} cost")
        curves = []
        for period in snapshot.bids[unit.unit_id]:
            if len(period.segments) > snapshot.limits.max_segments:
                raise ValueError("Historical bid exceeds the PMSS segment limit")
            for segment in period.segments:
                if (
                    snapshot.limits.price_floor is not None
                    and segment.price < snapshot.limits.price_floor
                ) or (
                    snapshot.limits.price_ceiling is not None
                    and segment.price > snapshot.limits.price_ceiling
                ):
                    # Historical evidence is immutable: report a current-rule
                    # mismatch without rewriting a genuine observed quote.
                    historical_price_rule_warnings += 1
            curves.append(
                {
                    "startPeriod": period.start_period,
                    "endPeriod": period.end_period,
                    "segmentDatas": [
                        {
                            "segmentOrder": order,
                            "startPower": seg.start_power,
                            "endPower": seg.end_power,
                            "price": seg.price,
                        }
                        for order, seg in enumerate(period.segments, start=1)
                    ],
                }
            )
        for hour in range(1, 25):
            curve_for_period(snapshot.bids[unit.unit_id], hour)
        safe_bids[unit.unit_id] = {"datas": curves, **costs}
    lim = snapshot.limits
    safe_rules = {
        "spotList": [
            {
                "marketAtomType": "DA",
                "unitPowerDeclareSegmentConstraint": lim.max_segments,
                "priceLowerConstraint": lim.price_floor,
                "priceUpperConstraint": lim.price_ceiling,
                "useSameBiddingCurve": lim.same_curve,
            }
        ]
    }
    evidence = None
    if scene_constraint_evidence is not None:
        validate_scene_constraint_evidence(
            scene_constraint_evidence, expected_units=len(snapshot.units)
        )
        evidence = dict(scene_constraint_evidence)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "caseDate": case_date,
        "marketTypeAtom": "DA",
        "periodNum": 24,
        "units": {
            "power": "MW",
            "branchReactance": "PMSS relative p.u.",
            "lmp": "PMSS source price units (unverified)",
            "bidCost": "PMSS source cost units (unverified)",
            "networkBaseMva": "computational normalization only",
        },
        "unitTree": safe_units,
        "unitBids": safe_bids,
        "marketSystem": safe_rules,
        "demandForecastMw": demand,
        "forecastSource": label,
        "loadSourceKind": "PMSS_DA_SCENE_LOAD_INPUT",
        "historicalBacktestOnly": True,
        "loadNodeCount": len(buses),
        "dcNetwork": network,
        "results": results,
        "generatorConstraints": {
            "bidEnvelopeMw": [
                {
                    "unitId": unit.unit_id,
                    "declaredMinMw": unit.min_power_mw,
                    "declaredMaxMw": unit.capacity_mw,
                }
                for unit in snapshot.units
            ],
            "sceneConstraintEvidence": evidence,
            "physicalUCVerified": False,
            "jointMilpReady": False,
            "physicalFieldsRequiringVerification": dict(FIELD_UNITS),
        },
        "importValidation": {
            "busCount": len(buses),
            "branchCount": len(branches),
            "generatorCount": len(snapshot.units),
            "hours": 24,
            "loadBusCount": len(network["hourlyDemandMw"]),
            "historicalUnitCount": len(results["unitResults"]),
            "historicalNodeCount": len(results["nodalPrices"]),
            "historicalBranchCount": len(results["branchFlows"]),
            "caseBoundByOperator": True,
            "physicalUCVerified": False,
            "pmssClearingParityVerified": False,
            "historicalPriceRuleBoundWarnings": historical_price_rule_warnings,
        },
    }


def read_live_standard_pmss_model(
    adapter: TeacherPlatformAdapter,
    *,
    context: TeacherPlatformContext,
    case: Mapping[str, Any],
    private_grid: Mapping[str, Any],
    grid_case_date: str,
    include_scene_evidence: bool = True,
) -> dict[str, Any]:
    """Read only through the established PMSS adapter; never call mutations."""
    source = build_da_scene_snapshot(adapter, context=context, case=case, include_results=True)
    evidence = None
    if include_scene_evidence:
        scene_id = str(case["pmSceneId"])
        evidence = summarize_scene_constraint_evidence(
            adapter.get_scene_unit_constraints(scene_id=scene_id),
            adapter.get_unit_initial_state_inputs(
                scene_id=scene_id,
                project_id=str(context.project["projectId"]),
                case_id=str(case["caseId"]),
            ),
            expected_units=len(context.units),
        )
    return build_standard_pmss_model(
        source,
        private_grid,
        grid_case_date=grid_case_date,
        scene_constraint_evidence=evidence,
    )
