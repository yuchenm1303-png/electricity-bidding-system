"""Anonymized aggregation of historical ORIGINAL-bid DC reconstruction errors.

Input DayValidation may contain private PMSS element IDs. This module
deliberately exports only cohort counts, period numbers, and numeric metrics.
The assessment is not validation of new bids or actual PMSS clearing.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from math import isfinite

from powerbid.historical_validation import (
    DayValidation,
    HourlyError,
    ValidationPolicy,
    ValidationVerdict,
)


def _maximum(values: Sequence[float | None]) -> float | None:
    valid = [v for v in values if v is not None and isfinite(v)]
    return max(valid) if valid else None


def _worst_hour(hours: Sequence[HourlyError], attribute: str) -> dict | None:
    candidates = [
        (getattr(hour, attribute), hour.hour)
        for hour in hours if getattr(hour, attribute) is not None
    ]
    if not candidates:
        return None
    value, index = sorted(candidates, key=lambda x: (-x[0], x[1]))[0]
    return {"hour": index, "mae": value}


def _price_spatial_shape_summary(hours: Sequence[HourlyError]) -> dict:
    """Use the SAME nodes for raw and ex-post median-centered MAE.

    Only hours with >=2 price observations are eligible. Treat median price
    recentering as an explanatory upper bound, never forecastable accuracy.
    """
    eligible = [
        row for row in hours
        if row.nodal_price_compared_nodes_for_shape >= 2
        and row.nodal_price_mae is not None
        and row.nodal_price_median_centered_mae is not None
    ]
    count = sum(x.nodal_price_compared_nodes_for_shape for x in eligible)
    raw = (
        sum(x.nodal_price_mae * x.nodal_price_compared_nodes_for_shape
            for x in eligible) / count if count else None
    )
    centered = (
        sum(x.nodal_price_median_centered_mae *
            x.nodal_price_compared_nodes_for_shape for x in eligible) / count
        if count else None
    )
    return {
        "spatiallyComparableHours": len(eligible),
        "spatiallyComparableNodeHours": count,
        "hoursWithoutEnoughObservedNodes": len(hours) - len(eligible),
        "hourlyUniformResidualHours": sum(
            x.nodal_price_uniform_shift_within_tolerance is True
            for x in eligible
        ),
        "worstObservedResidualRange": _maximum([
            x.nodal_price_residual_range for x in eligible
        ]),
        "rawMaeOnSameEligibleNodes": raw,
        "bestExPostHourlyUniformShiftMae": centered,
        "bestExPostUniformShiftReduction": (
            max(0.0, raw - centered) if raw is not None and centered is not None
            else None
        ),
        "bestExPostUniformShiftFraction": (
            max(0.0, min(1.0, (raw-centered)/raw))
            if raw is not None and centered is not None and raw > 1e-12 else None
        ),
        "exPostObservedPriceUsedToFitShift": True,
        "safeForForwardNodalPriceCalibration": False,
        "notEvidenceOfPMSSPriceCapOrSettlementMechanism": True,
    }


def anonymized_error_profile(
    days: Sequence[DayValidation],
    verdict: ValidationVerdict,
    policy: ValidationPolicy,
) -> dict:
    """Summarize all unit/node/branch maxima without exposing element IDs."""
    ordered = sorted(days, key=lambda d: d.case_date)
    if not ordered or len(set(d.case_date for d in ordered)) != len(ordered):
        raise ValueError("At least one unique historical day is required")
    records = []
    for day in ordered:
        if len(day.hourly_profile) != 24 or tuple(
            h.hour for h in day.hourly_profile
        ) != tuple(range(1, 25)):
            raise ValueError("Complete hourly diagnostics are required")
        records.append({
            "caseDate": day.case_date,
            "generatorCount": day.unit_count,
            "nodeCount": day.bus_count,
            "lineCount": day.branch_count,
            "mae": {
                "dispatchMw": day.unit_dispatch.mae,
                "nodalPrice": day.nodal_price.mae,
                "absoluteLineFlowMw": day.line_flow_abs.mae,
            },
            "coverage": {
                "dispatch": day.unit_dispatch.coverage,
                "nodalPrice": day.nodal_price.coverage,
                "absoluteLineFlow": day.line_flow_abs.coverage,
            },
            "worstElementDailyMae": {
                "unitMw": _maximum([x.dispatch.mae for x in day.per_unit]),
                "nodePrice": _maximum([x.metric.mae for x in day.per_node]),
                "lineAbsFlowMw": _maximum([x.metric.mae for x in day.per_branch]),
            },
            "worstElementAnyHourAbsoluteError": {
                "unitMw": _maximum([x.max_abs_error_mw for x in day.per_unit]),
                "nodePrice": _maximum([x.max_abs_error for x in day.per_node]),
                "lineAbsFlowMw": _maximum([x.max_abs_error for x in day.per_branch]),
            },
            "priceResidualStructure": _price_spatial_shape_summary(day.hourly_profile),
            "worstHourlyMae": {
                "unit": _worst_hour(day.hourly_profile, "unit_dispatch_mae_mw"),
                "node": _worst_hour(day.hourly_profile, "nodal_price_mae"),
                "line": _worst_hour(day.hourly_profile, "line_flow_abs_mae_mw"),
            },
            "hours": [asdict(hour) for hour in day.hourly_profile],
        })
    return {
        "schemaVersion": 1,
        "status": "HISTORICAL_ORIGINAL_BID_ERROR_DIAGNOSTIC_ONLY",
        "researchThresholdsNotIndustryStandards": asdict(policy),
        "chronologicalTrainingDates": [
            d.case_date for d in ordered
            if d.case_date not in verdict.holdout_case_dates
        ],
        "untouchedHoldoutDates": list(verdict.holdout_case_dates),
        "validationStatus": verdict.status,
        "holdoutUnitMaeMw": verdict.holdout_unit_mae,
        "holdoutNodalPriceMae": verdict.holdout_nodal_price_mae,
        "validationReasons": list(verdict.reasons),
        "dates": records,
        "originalBidsOnly": True,
        "validatedNewBids": False,
        "pmssCounterfactualClearingPerformed": False,
        "priceRuleVerified": False,
        "exPostCommonShiftIsNotProspectivePriceCorrection": True,
        "jointUnitCommitmentVerified": False,
        "warning": (
            "Hourly errors and anonymized cohort maxima from local DC "
            "replay of original PMSS historical bids. No real PMSS re-clearing "
            "or candidate-bid profit assessment. A small error under an "
            "illustrative research threshold is not permission to trade. "
            "Any hourly common-price shift is fitted EX-POST to observed "
            "PMSS prices: it must never be used as an unseen-hour model "
            "correction or treated as proof of PMSS price caps."
        ),
    }
