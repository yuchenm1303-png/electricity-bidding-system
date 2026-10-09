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
        "jointUnitCommitmentVerified": False,
        "warning": (
            "Hourly errors and anonymized cohort maxima from local DC "
            "replay of original PMSS historical bids. No real PMSS re-clearing "
            "or candidate-bid profit assessment. A small error under an "
            "illustrative research threshold is not permission to trade."
        ),
    }
