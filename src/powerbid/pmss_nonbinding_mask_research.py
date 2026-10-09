"""TRAINING-ONLY audit for nonbinding observed-zero mask re-optimization.

An improved historical fit after forcing already-zero generators to zero
cannot establish a unit-commitment constraint: the original solution remains
feasible under those added bounds. Equal-cost redispatch can instead arise
from LP degeneracy/tie-selection or numerical perturbation. Never use
same-day observed zero-output masks as a forward-looking model input.

Only anonymized counts and scalar diagnostics are returned.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from math import isfinite
from typing import Any

from powerbid.expost_commitment_diagnostics import replay_zero_output_restriction
from powerbid.network_dispatch import network_from_dict


def _date(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("Historical dates must be canonical ISO YYYY-MM-DD")
    try:
        if date.fromisoformat(raw).isoformat() != raw:
            raise ValueError("Noncanonical case date")
    except (ValueError, TypeError) as exc:
        raise ValueError("Historical dates must be canonical ISO YYYY-MM-DD") from exc
    return raw


def _topology(raw: Mapping[str, Any]) -> tuple:
    network = network_from_dict(raw["dcNetwork"])
    return (
        tuple(sorted(network.buses)),
        tuple(sorted(network.unit_bus.items())),
        tuple(sorted((
            line.line_id, line.from_bus, line.to_bus,
            line.reactance_pu, line.limit_mw,
        ) for line in network.lines)),
        network.base_mva,
        network.slack_bus,
    )


def audit_training_only_nonbinding_masks(
    training_cases: Sequence[Mapping[str, Any]],
    *,
    holdout_start_date: str,
) -> dict[str, Any]:
    """Requires >=2 earlier dates; no holdout snapshot is accepted or read."""
    holdout_start_date = _date(holdout_start_date)
    if isinstance(training_cases, (str, bytes)) or not 2 <= len(training_cases) <= 12:
        raise ValueError("Require 2..12 historical original-bid training days")
    indexed = {}
    topology = None
    for raw in training_cases:
        if not isinstance(raw, Mapping) or raw.get("historicalBacktestOnly") is not True:
            raise ValueError("Require explicitly labeled historical training-only cases")
        case_date = _date(raw.get("caseDate"))
        if case_date >= holdout_start_date:
            raise ValueError("Future or held-out observations cannot enter training")
        if case_date in indexed:
            raise ValueError("Duplicate historical training dates")
        signature = _topology(raw)
        if topology is None:
            topology = signature
        elif signature != topology:
            raise ValueError("Training topology or physical network changed")
        indexed[case_date] = raw

    diagnostics = []
    for day in sorted(indexed):
        report = replay_zero_output_restriction(indexed[day])
        if (
            report.paired_hours + report.masked_infeasible_hours
            + report.missing_observation_hours != 24
        ):
            raise ValueError("Invalid training hour accounting")
        if (report.nonbinding_mask_hours + report.binding_mask_hours
                + report.no_zero_mask_hours != report.paired_hours):
            raise ValueError("Invalid binding / nonbinding hour counts")
        hourly = []
        for item in report.hours:
            if item.status != "PAIRED":
                hourly.append({
                    "hour": item.period,
                    "status": item.status,
                    "originalFeasibleUnderMask": None,
                    "maeDeltaAfterMaskMw": None,
                    "maxUnitReallocationMw": None,
                    "primaryBidCostDelta": None,
                })
            else:
                hourly.append({
                    "hour": item.period,
                    "status": "NONBINDING_REDISPATCH"
                    if item.nonbinding_redispatch
                    else ("NO_ZERO_OUTPUT_MASK" if item.observed_zero_mw_units == 0
                          else ("BINDING_MASK" if not item.baseline_already_satisfies_mask
                                else "NONBINDING_NO_REDISPATCH")),
                    "originalFeasibleUnderMask": item.baseline_already_satisfies_mask,
                    "maeDeltaAfterMaskMw": (
                        item.masked_dispatch_mae_mw - item.baseline_dispatch_mae_mw
                    ),
                    "maxUnitReallocationMw": item.maximum_unit_redispatch_mw,
                    "primaryBidCostDelta": item.masked_minus_baseline_offer_cost,
                })
        diagnostics.append({
            "caseDate": report.case_date,
            "comparedHours": report.paired_hours,
            "missingHours": report.missing_observation_hours,
            "infeasibleMaskedHours": report.masked_infeasible_hours,
            "observedZeroUnitHours": report.observed_zero_unit_hours,
            "baselinePositiveOnObservedZeroUnitHours": (
                report.baseline_positive_on_observed_zero_unit_hours
            ),
            "nonbindingMaskHours": report.nonbinding_mask_hours,
            "noZeroOutputMaskHours": report.no_zero_mask_hours,
            "nonbindingRedispatchHours": report.nonbinding_redispatch_hours,
            "bindingMaskHours": report.binding_mask_hours,
            "baselinePairedMaeMw": report.baseline_paired_dispatch_mae_mw,
            "maskedPairedMaeMw": report.masked_paired_dispatch_mae_mw,
            "apparentMaeGainInNonbindingRedispatchHoursMw": (
                report.nonbinding_redispatch_mean_mae_gain_mw
            ),
            "maxReallocationFromNonbindingMaskMw": (
                report.nonbinding_maximum_unit_redispatch_mw
            ),
            "maxAbsolutePrimaryBidCostGap": (
                report.max_absolute_primary_cost_difference
            ),
            "hours": hourly,
        })
        if len(hourly) != 24 or any(
            row["hour"] != i for i, row in enumerate(hourly, start=1)
        ):
            raise ValueError("Incomplete hourly training diagnostic")
        for row in hourly:
            cost = row["primaryBidCostDelta"]
            if cost is not None and not isfinite(cost):
                raise ValueError("Invalid cost diagnostic")
    return {
        "schemaVersion": 2,
        "status": "TRAINING_ONLY_EXPOST_NONBINDING_MASK_AUDIT",
        "trainingCaseDates": sorted(indexed),
        "holdoutStartDate": holdout_start_date,
        "holdoutObservationsRead": False,
        "sameGridTopology": True,
        "days": diagnostics,
        "physicalUnitOnOffStateVerified": False,
        "pmssUnitCommitmentRulesVerified": False,
        "modelAccuracyImprovementVerified": False,
        "safeForForwardModelCalibration": False,
        "validatedNewBids": False,
        "pmssWritePerformed": False,
        "warning": (
            "If the original LP solution already obeys all masked zero-output "
            "bounds, a changed dispatch from a new LP solve does NOT prove a "
            "binding start/stop or ramp constraint. Apparent fit gains can "
            "reflect equally optimal allocations or numerical sensitivity. "
            "All masks use EX-POST training-day observed PMSS zero MW: "
            "never feed them into forward forecasting or hidden holdout tuning."
        ),
    }
