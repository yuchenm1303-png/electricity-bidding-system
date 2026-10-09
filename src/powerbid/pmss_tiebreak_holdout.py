"""Train-day-ONLY deterministic DC tie-break convention selection.

Select a pre-declared allocation convention on chronologically earlier
historical-original-bid cases, then report its error on later untouched dates.
This evaluates ORIGINAL-bid dispatch reconstruction, NOT novel bid choices,
teacher's hidden dispatch ranking, realized profit or PMSS counterfactuals.

All individual unit IDs, nodal prices and raw offers stay in input memory;
only aggregate errors, dates and non-sensitive warnings leave this module.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from math import isfinite
from typing import Any

from powerbid.historical_tiebreak_audit import (
    HistoricalTieBreakStudy,
    audit_historical_tiebreaks,
)
from powerbid.network_dispatch import network_from_dict
from powerbid.pmss_integration import snapshot_from_pmss

# Candidate conventions MUST be declared before seeing any PMSS outcomes.
# Source-order LP is shown only as a benchmark: file ordering can change it.
_POLICIES = {
    "canonical_lp": "canonical_order_baseline_mae_mw",
    "unit_id_ascending": "ascending_dispatch_mae_mw",
    "unit_id_descending": "descending_dispatch_mae_mw",
}
_TIE_ORDER = tuple(_POLICIES)


def _date_key(raw: Mapping[str, Any]) -> str:
    value = raw.get("caseDate")
    if not isinstance(value, str):
        raise ValueError("Missing explicit caseDate")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Noncanonical case date")
    except (TypeError, ValueError) as exc:
        raise ValueError("Historical case dates must be YYYY-MM-DD") from exc
    return value


def _immutable_grid(raw: Mapping[str, Any]) -> tuple[Any, ...]:
    network = network_from_dict(raw["dcNetwork"])
    return (
        tuple(sorted(network.buses)),
        tuple(sorted(network.unit_bus.items())),
        tuple(sorted((
            line.line_id, line.from_bus, line.to_bus, line.reactance_pu, line.limit_mw
        ) for line in network.lines)),
        network.base_mva,
        network.slack_bus,
    )


def _bid_signature(raw: Mapping[str, Any]) -> str:
    # Date-independent and stable under source row permutations.
    market = snapshot_from_pmss(
        unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    bids = {
        uid: [asdict(period) for period in market.bids[uid]]
        for uid in sorted(market.bids)
    }
    return sha256(json.dumps(
        bids, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


def _weighted_error(
    reports: Sequence[HistoricalTieBreakStudy], field: str,
) -> float:
    # Strict coverage means no skipped hours, and every unit in every hour
    # contributes equally. Reject ambiguous partial/missing observations.
    count = sum(r.compared_hours * r.generator_count for r in reports)
    if count <= 0:
        raise ValueError("No independent PMSS dispatch observations")
    total = 0.0
    for report in reports:
        mean = getattr(report, field)
        if mean is None or not isfinite(mean) or mean < 0:
            raise ValueError("Historical error must be finite with full observations")
        total += mean * report.compared_hours * report.generator_count
    return total / count


def _summaries(
    reports: Sequence[HistoricalTieBreakStudy],
) -> dict[str, float]:
    return {
        name: _weighted_error(reports, attribute)
        for name, attribute in _POLICIES.items()
    }


def evaluate_heldout_tiebreak_rules(
    cases: Sequence[Mapping[str, Any]],
    *,
    holdout_dates: int = 1,
    min_training_improvement_mw: float = 1.0,
) -> dict[str, Any]:
    """No future leakage: select on first N-1 (or N-K) chronological days.

    The heldout case is only read after selecting an explicitly predetermined
    policy from the training reports; it does not choose the winner. Every
    selected policy is independent of generator-ID names or PMSS outcomes.
    """
    if (
        type(min_training_improvement_mw) not in (int, float)
        or not isfinite(min_training_improvement_mw)
        or not 0 < min_training_improvement_mw <= 100
    ):
        raise ValueError("Required training improvement must be in (0,100] MW")
    if isinstance(cases, (str, bytes)) or not 3 <= len(cases) <= 12:
        raise ValueError("Require 3..12 dated PMSS original-bid cases")
    if type(holdout_dates) is not int or not 1 <= holdout_dates <= len(cases)-2:
        raise ValueError("Require >=2 training dates and >=1 later holdout date")
    indexed: dict[str, Mapping[str, Any]] = {}
    for raw in cases:
        if not isinstance(raw, Mapping) or raw.get("historicalBacktestOnly") is not True:
            raise ValueError("Every case must be a historical-only PMSS snapshot")
        label = _date_key(raw)
        if label in indexed:
            raise ValueError("Duplicate case dates are not independent evidence")
        indexed[label] = raw
    days = sorted(indexed)
    grids = {_immutable_grid(indexed[d]) for d in days}
    if len(grids) != 1:
        raise ValueError("Grid/line/unit identities changed between days")
    signatures = [_bid_signature(indexed[d]) for d in days]
    same_bid_pairs = sum(
        signatures[i] == signatures[j]
        for i in range(len(signatures))
        for j in range(i+1, len(signatures))
    )

    train_dates = days[:-holdout_dates]
    test_dates = days[-holdout_dates:]
    training = tuple(audit_historical_tiebreaks(indexed[d]) for d in train_dates)
    # Selection LOCKED before computing heldout PMSS observations.
    for result in training:
        if result.compared_hours != 24 or result.examined_hours != 24:
            raise ValueError("Training set requires all 24 observed unit-hours")
    training_scores = _summaries(training)
    winner = min(_TIE_ORDER, key=lambda policy: (
        training_scores[policy], _TIE_ORDER.index(policy)
    ))

    testing = tuple(audit_historical_tiebreaks(indexed[d]) for d in test_dates)
    for result in testing:
        if result.compared_hours != 24 or result.examined_hours != 24:
            raise ValueError("Holdout requires complete 24h unit observations")
    testing_scores = _summaries(testing)
    train_margin = training_scores[winner] - training_scores["canonical_lp"]
    test_margin = testing_scores[winner] - testing_scores["canonical_lp"]

    # Per-DAY paired deltas prevent pooled unit-hour averages hiding a
    # failure concentrated in one day. All gate decisions use TRAINING only.
    # Later cases are observed strictly for descriptive validation.
    train_bids = signatures[:-holdout_dates]
    heldout_bids = signatures[-holdout_dates:]
    training_diversity = len(set(train_bids))
    reused_heldout = sum(s in set(train_bids) for s in heldout_bids)
    training_daily = []
    for i, report in enumerate(training):
        daily_scores = _summaries((report,))
        selected_delta = daily_scores[winner] - daily_scores["canonical_lp"]
        training_daily.append({
            "caseDate": train_dates[i],
            "maeMwByPolicy": daily_scores,
            "selectedVsCanonicalDeltaMaeMw": selected_delta,
            "selectedBetterThanCanonical": selected_delta < -1e-8,
            "identicalOfferCurveSeenEarlierInTraining": (
                train_bids[i] in train_bids[:i]
            ),
        })
    testing_daily = []
    for i, report in enumerate(testing):
        daily_scores = _summaries((report,))
        selected_delta = daily_scores[winner] - daily_scores["canonical_lp"]
        testing_daily.append({
            "caseDate": test_dates[i],
            "maeMwByPolicy": daily_scores,
            "selectedVsCanonicalDeltaMaeMw": selected_delta,
            "selectedBetterThanCanonical": selected_delta < -1e-8,
            "identicalOfferCurveSeenInTraining": heldout_bids[i] in train_bids,
        })

    # A reproducible, PREDECLARED minimum improvement helps prevent
    # a tiny solver-driven training MAE difference being called a priority
    # discovery. With only 2 training dates this is a cautious screening
    # criterion, NOT a significance test nor PMSS rule certification.
    reasons = []
    if winner == "canonical_lp":
        reasons.append("CANONICAL_ALREADY_TRAINING_BEST")
    if training_diversity < 2:
        reasons.append("TRAINING_OFFER_DIVERSITY_LT_2")
    if train_margin > -min_training_improvement_mw + 1e-10:
        reasons.append("POOLED_TRAINING_IMPROVEMENT_BELOW_THRESHOLD")
    if any(
        day["selectedVsCanonicalDeltaMaeMw"] >
        -min_training_improvement_mw + 1e-10
        for day in training_daily
    ):
        reasons.append("NOT_EVERY_TRAINING_DAY_IMPROVES_MATERIALLY")
    guardrail_pass = not reasons
    guarded_policy = winner if guardrail_pass else "canonical_lp"
    holdout_winner = min(_TIE_ORDER, key=lambda policy: (
        testing_scores[policy], _TIE_ORDER.index(policy)
    ))
    # Only dates and numerical aggregate MAEs are included; no machine IDs,
    # source raw rows, bid fingerprints or market credential information.
    return {
        "schemaVersion": 1,
        "status": "CHRONOLOGICAL_HOLDOUT_ORIGINAL_BID_RESEARCH_ONLY",
        "trainingCaseDates": train_dates,
        "untouchedHoldoutCaseDates": test_dates,
        "trainingCaseCount": len(train_dates),
        "holdoutCaseCount": len(test_dates),
        "trainingMaeMwByPolicy": training_scores,
        "holdoutMaeMwByPolicy": testing_scores,
        "policyLockedUsingTrainingOnly": winner,
        "holdoutBestPolicyExPostDiagnosticOnly": holdout_winner,
        "trainingSelectedVsCanonicalDeltaMaeMw": train_margin,
        "holdoutSelectedVsCanonicalDeltaMaeMw": test_margin,
        "holdoutSelectedBetterThanCanonical": test_margin < -1e-8,
        "sourceOrderReferenceHoldoutMaeMw": _weighted_error(
            testing, "source_order_baseline_mae_mw"
        ),
        "distinctCaseDates": len(days),
        "identicalOriginalBidPairsAcrossDates": same_bid_pairs,
        "trainingDistinctOriginalBidCurves": training_diversity,
        "holdoutDistinctOriginalBidCurves": len(set(heldout_bids)),
        "holdoutDatesReusingTrainingBidCurves": reused_heldout,
        "trainingDailyDiagnostics": training_daily,
        "holdoutDailyDiagnostics": testing_daily,
        "trainingSelectedDaysBetterThanCanonical": sum(
            day["selectedBetterThanCanonical"] for day in training_daily
        ),
        "holdoutSelectedDaysBetterThanCanonical": sum(
            day["selectedBetterThanCanonical"] for day in testing_daily
        ),
        "largestHoldoutDeteriorationMaeMw": max(
            0.0, *(day["selectedVsCanonicalDeltaMaeMw"] for day in testing_daily)
        ),
        "predeclaredTrainingGuardrail": {
            "minimumMeaningfulImprovementMw": min_training_improvement_mw,
            "requiresAllTrainingDaysAndTwoDistinctOfferCurves": True,
            "passed": guardrail_pass,
            "reasons": reasons,
            "trainingOnlyConservativeComparator": guarded_policy,
        },
        "holdoutRobustnessAssessment": (
            "ONLY_ONE_HOLDOUT_DATE_NO_STATISTICAL_CONFIDENCE"
            if len(test_dates) == 1 else
            "DESCRIPTIVE_MULTIDAY_HOLDOUT_NO_STATISTICAL_CONFIDENCE"
        ),
        "statisticalSignificanceEstablished": False,
        "readyForForwardBidOptimization": False,
        "sameTopology": True,
        "fullObservedDispatchCoverage": True,
        "selectionUsesHoldoutObservations": False,
        "heldoutCasesContainOnlyHistoricalOriginalBids": True,
        "validatedNewBids": False,
        "pmssWritePerformed": False,
        "pmssClearingExecuted": False,
        "actualPMSSRankingRuleVerified": False,
        "profitPredictionVerified": False,
        "warning": (
            "An earlier-day selected ID tie-break is only a DC surrogate "
            "reconstruction convention. Holdout uses recorded ORIGINAL bids, "
            "not counterfactual PMSS clearing of a new bid. Same bid curves "
            "across different days reduce offer diversity. No live strategy "
            "or profit claim follows from lower reconstruction MAE."
        ),
    }
