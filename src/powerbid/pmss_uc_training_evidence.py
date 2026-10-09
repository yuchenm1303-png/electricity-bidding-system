"""Offline training-only PMSS scene and dispatch-temporal evidence.

Validates an authorized saved T200 calculation page against exact original
generator identities, then measures historical hour-to-hour generation
changes on earlier-day ORIGINAL-bid DC replays. This is descriptive EX-POST
evidence, NOT thermal-constraint inference or a PMSS clearing reproduction.
Only anonymized fields leave this module. No network/API/platform access.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from math import isfinite
from typing import Any

from powerbid.network_dispatch import DcOffer, dc_clear_hour, network_from_dict
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_diagnostics import series24
from powerbid.pmss_integration import curve_for_period, snapshot_from_pmss
from powerbid.pmss_scene_constraint_evidence import INITIAL_FIELDS, SWITCHES

ZERO_MW_TOLERANCE = 1e-6


def _date(raw: Any) -> str:
    if type(raw) is not str:
        raise ValueError("Expected canonical ISO YYYY-MM-DD")
    try:
        if date.fromisoformat(raw).isoformat() != raw:
            raise ValueError("Noncanonical ISO date")
    except (ValueError, TypeError) as exc:
        raise ValueError("Expected canonical ISO YYYY-MM-DD") from exc
    return raw


def _grid_signature(raw: Mapping[str, Any]) -> tuple:
    network = network_from_dict(raw["dcNetwork"])
    return (
        tuple(sorted(network.buses)),
        tuple(sorted(network.unit_bus.items())),
        tuple(sorted(
            (line.line_id, line.from_bus, line.to_bus,
             line.reactance_pu, line.limit_mw)
            for line in network.lines
        )),
        network.base_mva,
        network.slack_bus,
    )


def _records(raw: Any, label: str, count: int) -> list[dict[str, Any]]:
    if (not isinstance(raw, Mapping) or raw.get("http") != 200
            or raw.get("code") != "T200"):
        raise ValueError(f"{label}: only completed T200 source responses accepted")
    page = raw.get("data")
    if (not isinstance(page, Mapping) or type(page.get("rowCount")) is not int
            or page["rowCount"] != count or page.get("pageNum") != 1
            or page.get("totalPage") != 1):
        raise ValueError(f"{label}: incomplete or ambiguous PMSS source page")
    rows = page.get("datas")
    if (not isinstance(rows, list) or len(rows) != count
            or not all(isinstance(row, dict) for row in rows)):
        raise ValueError(f"{label}: expected all generator records")
    return rows


def _matching_ids(rows: Sequence[Mapping[str, Any]], expected: set[str]) -> None:
    unit_ids = [row.get("unitId") for row in rows]
    if (len(unit_ids) != len(expected)
            or any(type(uid) is not str or not uid for uid in unit_ids)
            or set(unit_ids) != expected):
        raise ValueError("Scene record unit identities differ from original bid cases")


def _switch_code(raw: Any) -> str:
    if type(raw) in (int, str) and str(raw) in ("0", "1"):
        return "code_" + str(raw)
    if raw is None:
        return "missing"
    return "other"


def _percentile(values: Sequence[float], percentage: float) -> float | None:
    """Simple nearest-rank descriptive percentile, not a physical bound."""
    if not values:
        return None
    return sorted(values)[max(0, min(
        len(values)-1, int((len(values) * percentage + 99) // 100) - 1
    ))]


def _temporal_training_day(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Read the original bid curve and its same-day historical output once."""
    market = snapshot_from_pmss(
        unit_tree=raw["unitTree"],
        unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    grid = network_from_dict(raw["dcNetwork"])
    verify_network_inputs(market, grid, market.units[0].unit_id)
    ids = {unit.unit_id for unit in market.units}
    observed = raw.get("results")
    if (not isinstance(observed, Mapping)
            or observed.get("marketTypeAtom") != "DA"
            or observed.get("periodNum") != 24):
        raise ValueError("Require complete original DA historical results")
    rows = observed.get("unitResults")
    if not isinstance(rows, list) or len(rows) != len(ids):
        raise ValueError("Require exactly one observed row per generator")
    actual: dict[str, tuple[float | None, ...]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or (
            row.get("market_type") or row.get("marketTypeAtom")
        ) != "DA":
            raise ValueError("Unexpected historical market or result row")
        uid = row.get("unit_id") or row.get("element_id") or row.get("elementId")
        if type(uid) is not str or uid in actual:
            raise ValueError("Missing or duplicate observed generator ID")
        actual[uid] = series24(row, "accepted_mw", "power")
    if set(actual) != ids:
        raise ValueError("Observed and original-bid unit IDs disagree")
    for values in actual.values():
        if any(x is not None and (not isfinite(x) or x < 0) for x in values):
            raise ValueError("Historical power must be finite nonnegative")

    modeled: dict[str, list[float]] = {uid: [] for uid in ids}
    for hour in range(1, 25):
        offers = [
            DcOffer(unit.unit_id, index, segment.quantity_mw, segment.price)
            for unit in market.units
            for index, segment in enumerate(
                curve_for_period(market.bids[unit.unit_id], hour), start=1
            )
        ]
        solution = dc_clear_hour(grid, offers, hour)
        for uid in ids:
            modeled[uid].append(solution.accepted_by_unit[uid])
    actual_changes: list[float] = []
    model_changes: list[float] = []
    changes_error: list[float] = []
    continuously_positive_abs: list[float] = []
    positive_to_zero = zero_to_positive = 0
    mode_positive_to_zero = mode_zero_to_positive = 0
    disagreeing_crossings = 0
    available_pairs = 0
    missing_pairs = 0
    for uid in ids:
        values = actual[uid]
        predictions = modeled[uid]
        for idx in range(1, 24):
            a, b = values[idx - 1], values[idx]
            if a is None or b is None:
                missing_pairs += 1
                continue
            available_pairs += 1
            actual_delta = b - a
            model_delta = predictions[idx] - predictions[idx - 1]
            actual_changes.append(abs(actual_delta))
            model_changes.append(abs(model_delta))
            changes_error.append(abs(actual_delta - model_delta))
            was_positive = a > ZERO_MW_TOLERANCE
            is_positive = b > ZERO_MW_TOLERANCE
            model_was_positive = predictions[idx - 1] > ZERO_MW_TOLERANCE
            model_is_positive = predictions[idx] > ZERO_MW_TOLERANCE
            positive_to_zero += int(was_positive and not is_positive)
            zero_to_positive += int(not was_positive and is_positive)
            mode_positive_to_zero += int(
                model_was_positive and not model_is_positive
            )
            mode_zero_to_positive += int(
                not model_was_positive and model_is_positive
            )
            disagreeing_crossings += int(
                (was_positive, is_positive)
                != (model_was_positive, model_is_positive)
                and (was_positive != is_positive
                     or model_was_positive != model_is_positive)
            )
            if was_positive and is_positive:
                continuously_positive_abs.append(abs(actual_delta))
    expected_pairs = len(ids) * 23
    assert available_pairs + missing_pairs == expected_pairs
    return {
        "date": raw["caseDate"],
        "unitCount": len(ids),
        "expectedAdjacentUnitPairs": expected_pairs,
        "observedAdjacentUnitPairs": available_pairs,
        "missingAdjacentUnitPairs": missing_pairs,
        "historicalAbsoluteHourlyDeltaMwP95": _percentile(
            actual_changes, 95
        ),
        "historicalAbsoluteHourlyDeltaMwMax": max(actual_changes, default=None),
        "historicalContinuouslyPositiveDeltaMwMax": max(
            continuously_positive_abs, default=None
        ),
        "localDcAbsoluteHourlyDeltaMwP95": _percentile(model_changes, 95),
        "pairedDeltaDifferenceMaeMw": (
            sum(changes_error) / len(changes_error)
            if changes_error else None
        ),
        "pairedDeltaDifferenceMaxMw": max(changes_error, default=None),
        "observedZeroToPositiveEvents": zero_to_positive,
        "observedPositiveToZeroEvents": positive_to_zero,
        "localDcZeroToPositiveEvents": mode_zero_to_positive,
        "localDcPositiveToZeroEvents": mode_positive_to_zero,
        "crossingClassificationDisagreements": disagreeing_crossings,
    }


def audit_training_scene_and_temporal_evidence(
    training_cases: Sequence[Mapping[str, Any]],
    saved_scene_capture: Mapping[str, Any],
    *,
    holdout_start_date: str,
) -> dict[str, Any]:
    """Fail closed before viewing any held-out records; scene codes stay raw."""
    holdout_start_date = _date(holdout_start_date)
    if (isinstance(training_cases, (str, bytes))
            or not 2 <= len(training_cases) <= 12):
        raise ValueError("Require 2..12 earlier historical training snapshots")
    indexed: dict[str, Mapping[str, Any]] = {}
    signature = None
    unit_ids = None
    for raw in training_cases:
        if not isinstance(raw, Mapping) or raw.get("historicalBacktestOnly") is not True:
            raise ValueError("Only historical original-bid training snapshots accepted")
        label = _date(raw.get("caseDate"))
        if label >= holdout_start_date:
            raise ValueError("Holdout or future date cannot be read into training")
        if label in indexed:
            raise ValueError("Duplicate training dates are not independent evidence")
        current = _grid_signature(raw)
        if signature is None:
            signature = current
        elif current != signature:
            raise ValueError("Physical network changed between training snapshots")
        market = snapshot_from_pmss(
            unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
            market_system=raw["marketSystem"],
            demand_forecast_mw=raw["demandForecastMw"],
            forecast_source=raw["forecastSource"],
        )
        actual_ids = {u.unit_id for u in market.units}
        if unit_ids is None:
            unit_ids = actual_ids
        elif unit_ids != actual_ids:
            raise ValueError("Generator identities changed across training dates")
        indexed[label] = raw
    if not isinstance(saved_scene_capture, Mapping) or unit_ids is None:
        raise ValueError("Missing authorized saved scene capture")
    rows = _records(saved_scene_capture.get("calculation"), "calculation", len(unit_ids))
    _matching_ids(rows, unit_ids)
    scene_ids = [row.get("sceneId") for row in rows]
    if any(type(s) is not str or not s for s in scene_ids) or len(set(scene_ids)) != 1:
        raise ValueError("Inconsistent or missing scene origin within saved page")
    flags = {}
    for key in SWITCHES:
        counts = Counter(_switch_code(row.get(key)) for row in rows)
        flags[key] = {
            code: counts[code] for code in ("code_0", "code_1", "missing", "other")
        }
    initial_capture = saved_scene_capture.get("initial")
    initial_complete = False
    if (isinstance(initial_capture, Mapping)
            and initial_capture.get("code") == "T200"
            and initial_capture.get("http") == 200):
        initial_rows = _records(initial_capture, "initial", len(unit_ids))
        _matching_ids(initial_rows, unit_ids)
        if any(not set(INITIAL_FIELDS) <= row.keys() for row in initial_rows):
            raise ValueError("Independent initial-state page lacks required fields")
        initial_complete = True
    training = [_temporal_training_day(indexed[d]) for d in sorted(indexed)]
    return {
        "schemaVersion": 1,
        "status": "OBSERVED_TRAINING_SCENE_UC_READINESS_BLOCKED",
        "trainingCaseDates": sorted(indexed),
        "heldoutStartDate": holdout_start_date,
        "holdoutObservedDispatchRead": False,
        "observedSceneGeneratorRows": len(rows),
        "sceneUnitIdentityMatchesHistoricalBids": True,
        "savedSceneOneConsistentSourceId": True,
        "independentlyAuthenticatedSameCase": False,
        "sceneCalculationT200": True,
        "initialStateIndependentT200Complete": initial_complete,
        "rawSwitchCodeCounts": flags,
        "hourlyObservations": training,
        "unresolvedUcEvidence": [
            "FLAG_CODE_TO_PHYSICAL_MEANING_UNVERIFIED",
            "RAMP_RATE_UNITS_AND_APPLICABILITY_UNVERIFIED",
            "INITIAL_ON_OFF_STATE_SEMANTICS_UNVERIFIED",
            "INITIAL_STATE_DURATION_UNVERIFIED",
            "STARTUP_SHUTDOWN_RAMPS_AND_COSTS_UNVERIFIED",
            "MINIMUM_ON_OFF_TIME_RULES_UNVERIFIED",
        ] + ([] if initial_complete else ["INDEPENDENT_INITIAL_STATE_PAGE_UNAVAILABLE"]),
        "thermalConstraintsProduced": False,
        "jointMilpReady": False,
        "trainedPredictiveUcModel": False,
        "validatedNewBidRevenue": False,
        "pmssWritePerformed": False,
        "warning": (
            "T200 confirms one saved business-response page, NOT physical "
            "interpretation, authenticity of case binding, or future readiness. "
            "Observed 0-to-positive power transitions are not proven machine "
            "startups; measured consecutive MW changes are not certified ramp "
            "limits. Historical outcomes cannot be used to calibrate or "
            "score on the untouched heldout date. No PMSS API calls or writes."
        ),
    }
