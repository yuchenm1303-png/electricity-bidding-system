"""De-identified cross-day diagnostic of ORIGINAL PMSS bids, never new quotes.

Each input is an independently dated, fully populated historical read-only
PMSS snapshot. All market clearing uses the local DC surrogate. The
fixed-injection comparison uses observed unit dispatch to diagnose flow
sensitivity. It cannot prove which market or power-flow assumptions caused
the residual, and cannot certify counterfactual bidding outcomes.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from powerbid.flow_error_attribution import compare_dispatch_and_network_sources


def summarize_crossday_history(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Output ONLY aggregate, credential-free diagnostics; no unit IDs or bids."""
    if isinstance(cases, (str, bytes)) or not 3 <= len(cases) <= 20:
        raise ValueError("Need 3..20 independent dated PMSS historical snapshots")
    indexed: dict[str, Any] = {}
    for raw in cases:
        if not isinstance(raw, Mapping):
            raise ValueError("Each PMSS historical snapshot must be an object")
        label = raw.get("caseDate")
        if not isinstance(label, str):
            raise ValueError("Historical snapshot requires caseDate")
        try:
            valid = date.fromisoformat(label).isoformat() == label
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("Historical caseDate must be ISO YYYY-MM-DD")
        if label in indexed:
            raise ValueError("Duplicate case dates cannot be counted as independent")
        indexed[label] = compare_dispatch_and_network_sources(dict(raw))

    ordered = [indexed[key] for key in sorted(indexed)]
    fingerprints = {item.independent_dispatch.grid_fingerprint for item in ordered}
    if len(fingerprints) != 1:
        raise ValueError("Topology changed; do not pool different DC networks")

    days: list[dict[str, Any]] = []
    for record in ordered:
        day = record.independent_dispatch
        comparison = record.comparison
        fixed = record.observed_dispatch
        days.append({
            "caseDate": day.case_date,
            "unitCount": day.unit_count,
            "nodeCount": day.bus_count,
            "branchCount": day.branch_count,
            "hourCount": 24,
            "observedDemandMwh": day.total_demand_mwh,
            "originalBidDcUnitDispatchMaeMw": day.unit_dispatch.mae,
            "originalBidDcNodePriceMae": day.nodal_price.mae,
            "originalBidDcLineFlowAbsMaeMw": day.line_flow_abs.mae,
            "fixedObservedDispatchLineFlowAbsMaeMw": (
                fixed.flow_magnitude_mae_mw
            ),
            "fixedObservedDispatchHours": fixed.modeled_hours,
            "missingDispatchHours": fixed.missing_injection_hours,
            "unbalancedDispatchHours": fixed.unbalanced_injection_hours,
            "sameObservationSet": comparison.same_observation_set,
            "relativeLineFlowMaeFixedVsRecleared": (
                comparison.remaining_error_ratio
                if comparison.same_observation_set else None
            ),
            "unitDispatchCoverage": day.unit_dispatch.coverage,
            "nodePriceCoverage": day.nodal_price.coverage,
            "lineFlowCoverage": day.line_flow_abs.coverage,
            "fixedObservedDispatchLineCoverage": (
                fixed.observed_line_points / fixed.expected_line_points
                if fixed.expected_line_points else 0.0
            ),
        })
    return {
        "schemaVersion": 1,
        "status": "DESCRIPTIVE_HISTORICAL_RESEARCH_ONLY",
        "independentDateCount": len(days),
        "sameGridFingerprint": True,
        "latestDateHeldOutForDescriptiveComparison": days[-1]["caseDate"],
        "noModelTrainingPerformed": True,
        "teacherPlatformWritesPerformed": False,
        "actualPmssClearingExecuted": False,
        "validatedNewBids": False,
        "independentPmssModelSemanticsVerified": False,
        "warning": (
            "Original-bid historical DC surrogate only, not real PMSS "
            "counterfactual clearing. Holding observed generator dispatch fixed "
            "is conditional diagnosis, NOT causal attribution or profit evidence. "
            "Distinct case dates do not imply distinct original bid curves."
        ),
        "days": days,
    }
