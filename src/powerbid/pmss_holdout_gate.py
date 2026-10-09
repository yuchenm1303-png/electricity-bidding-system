"""Fail-closed, read-only *retrospective* review of sanitized PMSS holdout reports.

This accepts ONLY an anonymous report emitted by our historical original-bid
tie-break tool. It independently reconstructs the training-only selection,
guardrail and held-out deltas from daily aggregates. It NEVER signs source
authenticity, authorizes live bidding, or improves the out-of-sample model.
"""
from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any

POLICIES = ("canonical_lp", "unit_id_ascending", "unit_id_descending")
FALSE_CLAIMS = (
    "selectionUsesHoldoutObservations",
    "validatedNewBids",
    "pmssWritePerformed",
    "pmssClearingExecuted",
    "actualPMSSRankingRuleVerified",
    "profitPredictionVerified",
    "statisticalSignificanceEstablished",
    "readyForForwardBidOptimization",
    "conservativeComparatorEligibleForLivePMSS",
)
ROOT_KEYS = frozenset((
    "schemaVersion", "status", "secondaryOptimizationCostToleranceAbs",
    "secondaryOptimizationCostToleranceRel", "maximumObservedSecondaryCostDifference",
    "trainingCaseDates", "untouchedHoldoutCaseDates", "trainingCaseCount",
    "holdoutCaseCount", "trainingMaeMwByPolicy", "holdoutMaeMwByPolicy",
    "policyLockedUsingTrainingOnly", "holdoutBestPolicyExPostDiagnosticOnly",
    "trainingSelectedVsCanonicalDeltaMaeMw", "holdoutSelectedVsCanonicalDeltaMaeMw",
    "trainingConservativeComparatorMaeMw", "holdoutConservativeComparatorMaeMw",
    "trainingConservativeVsCanonicalDeltaMaeMw",
    "holdoutConservativeVsCanonicalDeltaMaeMw",
    "holdoutConservativeDaysBetterThanCanonical",
    "largestHoldoutConservativeDeteriorationMaeMw",
    "conservativeComparatorLockedBeforeHoldout",
    "conservativeComparatorEligibleForLivePMSS",
    "holdoutSelectedBetterThanCanonical", "sourceOrderReferenceHoldoutMaeMw",
    "distinctCaseDates", "identicalOriginalBidPairsAcrossDates",
    "trainingDistinctOriginalBidCurves", "holdoutDistinctOriginalBidCurves",
    "holdoutDatesReusingTrainingBidCurves", "trainingDailyDiagnostics",
    "holdoutDailyDiagnostics", "trainingSelectedDaysBetterThanCanonical",
    "holdoutSelectedDaysBetterThanCanonical", "largestHoldoutDeteriorationMaeMw",
    "predeclaredTrainingGuardrail", "holdoutRobustnessAssessment",
    "statisticalSignificanceEstablished", "readyForForwardBidOptimization",
    "sameTopology", "fullObservedDispatchCoverage",
    "selectionUsesHoldoutObservations", "heldoutCasesContainOnlyHistoricalOriginalBids",
    "validatedNewBids", "pmssWritePerformed", "pmssClearingExecuted",
    "actualPMSSRankingRuleVerified", "profitPredictionVerified", "warning",
))
DAILY_TRAIN = frozenset((
    "caseDate", "maeMwByPolicy", "selectedVsCanonicalDeltaMaeMw",
    "selectedBetterThanCanonical", "identicalOfferCurveSeenEarlierInTraining",
))
DAILY_TEST = frozenset((
    "caseDate", "maeMwByPolicy", "selectedVsCanonicalDeltaMaeMw",
    "selectedBetterThanCanonical", "guardedVsCanonicalDeltaMaeMw",
    "guardedBetterThanCanonical", "identicalOfferCurveSeenInTraining",
))
GUARD_KEYS = frozenset((
    "minimumMeaningfulImprovementMw",
    "requiresAllTrainingDaysAndTwoDistinctOfferCurves",
    "passed", "reasons", "trainingOnlyConservativeComparator",
))


def _number(value: Any, name: str) -> float:
    if type(value) not in (float, int) or not isfinite(value) or not 0 <= value <= 1e10:
        raise ValueError(f"{name}: expected nonnegative finite numeric aggregate")
    return float(value)


def _same(a: float, b: float, name: str) -> None:
    if abs(a - b) > 1e-6 + 1e-9 * max(abs(a), abs(b)):
        raise ValueError(f"{name}: inconsistent daily versus pooled aggregate")


def _dates(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise ValueError(f"{name}: require a bounded case date list")
    checked = []
    for item in value:
        if type(item) is not str or len(item) != 10:
            raise ValueError(f"{name}: invalid case date format")
        try:
            if date.fromisoformat(item).isoformat() != item:
                raise ValueError("Noncanonical date")
        except ValueError as exc:
            raise ValueError(f"{name}: invalid case date") from exc
        checked.append(item)
    if sorted(set(checked)) != checked:
        raise ValueError(f"{name}: dates must be unique and chronological")
    return checked


def _scores(value: Any, name: str) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != set(POLICIES):
        raise ValueError(f"{name}: expected exactly three predeclared strategies")
    return {policy: _number(value[policy], name) for policy in POLICIES}


def _days(value: Any, dates: list[str], keyset: frozenset[str],
          selected: str, guarded: str, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(dates):
        raise ValueError(f"{name}: each case date must have one diagnostic row")
    days = []
    for pos, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != keyset:
            raise ValueError(f"{name}: unknown or missing per-day fields")
        if item["caseDate"] != dates[pos]:
            raise ValueError(f"{name}: per-day order differs from dated split")
        scores = _scores(item["maeMwByPolicy"], name)
        delta = scores[selected] - scores["canonical_lp"]
        recorded = item["selectedVsCanonicalDeltaMaeMw"]
        if type(recorded) not in (int, float) or not isfinite(recorded):
            raise ValueError(f"{name}: invalid signed change in MAE")
        _same(delta, float(recorded), name)
        if item["selectedBetterThanCanonical"] is not (delta < -1e-8):
            raise ValueError(f"{name}: selected improvement flag is inconsistent")
        guarded_delta = scores[guarded] - scores["canonical_lp"]
        if "guardedVsCanonicalDeltaMaeMw" in item:
            recorded_guard = item["guardedVsCanonicalDeltaMaeMw"]
            if type(recorded_guard) not in (int, float) or not isfinite(recorded_guard):
                raise ValueError(f"{name}: invalid guarded MAE change")
            _same(guarded_delta, float(recorded_guard), name)
            if item["guardedBetterThanCanonical"] is not (guarded_delta < -1e-8):
                raise ValueError(f"{name}: guarded improvement flag is inconsistent")
        days.append({"scores": scores, "selectedDelta": delta,
                     "guardedDelta": guarded_delta})
    return days


def _average(days: list[dict[str, Any]], policy: str) -> float:
    return sum(day["scores"][policy] for day in days) / len(days)


def review_holdout_report(raw: Any) -> dict[str, Any]:
    """Validate internal arithmetic before stating a conservative conclusion.

    This is a CHECK of data supplied by a user, not cryptographic verification
    that it actually came from the teacher's system or the historical solver.
    """
    if not isinstance(raw, dict) or set(raw) != ROOT_KEYS:
        raise ValueError("Expected an unchanged, anonymized V1 PowerBid holdout report")
    if type(raw["schemaVersion"]) is not int or raw["schemaVersion"] != 1 or (
        raw["status"] != "CHRONOLOGICAL_HOLDOUT_ORIGINAL_BID_RESEARCH_ONLY"
    ):
        raise ValueError("Unsupported historical-only report version/status")
    if any(raw[k] is not False for k in FALSE_CLAIMS):
        raise ValueError("Report attempts to claim unsupported PMSS readiness")
    if raw["conservativeComparatorLockedBeforeHoldout"] is not True or (
        raw["sameTopology"] is not True
        or raw["fullObservedDispatchCoverage"] is not True
        or raw["heldoutCasesContainOnlyHistoricalOriginalBids"] is not True
    ):
        raise ValueError("Historical holdout split, coverage or locking not guaranteed")
    train = _dates(raw["trainingCaseDates"], "training dates")
    test = _dates(raw["untouchedHoldoutCaseDates"], "holdout dates")
    if len(train) < 2 or len(train)+len(test) > 12 or train[-1] >= test[0]:
        raise ValueError("Holdout must be later than two or more training dates")
    for flag, count in (("trainingCaseCount", len(train)),
                        ("holdoutCaseCount", len(test)),
                        ("distinctCaseDates", len(train)+len(test))):
        if type(raw[flag]) is not int or raw[flag] != count:
            raise ValueError(f"{flag}: inconsistent number of distinct cases")
    if raw["policyLockedUsingTrainingOnly"] not in POLICIES:
        raise ValueError("Selected research policy not in prespecified candidate set")
    winner = raw["policyLockedUsingTrainingOnly"]
    guard = raw["predeclaredTrainingGuardrail"]
    if not isinstance(guard, dict) or set(guard) != GUARD_KEYS:
        raise ValueError("Missing original predeclared training guard")
    threshold = _number(guard["minimumMeaningfulImprovementMw"], "threshold")
    if not 0 < threshold <= 100:
        raise ValueError("Training margin must be positive and bounded")
    if guard["requiresAllTrainingDaysAndTwoDistinctOfferCurves"] is not True:
        raise ValueError("Training diversity/no-harm condition cannot be waived")
    conservative = guard["trainingOnlyConservativeComparator"]
    if conservative not in POLICIES:
        raise ValueError("Unknown guarded comparator")
    day_train = _days(raw["trainingDailyDiagnostics"], train, DAILY_TRAIN,
                      winner, conservative, "training")
    train_scores = _scores(raw["trainingMaeMwByPolicy"], "training aggregate")
    for key in POLICIES:
        _same(train_scores[key], _average(day_train, key), "training aggregate")
    calculated_winner = min(POLICIES, key=lambda p: (
        train_scores[p], POLICIES.index(p)
    ))
    if calculated_winner != winner:
        raise ValueError("Training winner differs from independently recomputed winner")

    distinct_train = raw["trainingDistinctOriginalBidCurves"]
    if (type(distinct_train) is not int or
            not 1 <= distinct_train <= len(train)):
        raise ValueError("Training offer diversity count invalid")
    margin = train_scores[winner] - train_scores["canonical_lp"]
    reasons = []
    if winner == "canonical_lp":
        reasons.append("CANONICAL_ALREADY_TRAINING_BEST")
    if distinct_train < 2:
        reasons.append("TRAINING_OFFER_DIVERSITY_LT_2")
    if margin > -threshold + 1e-10:
        reasons.append("POOLED_TRAINING_IMPROVEMENT_BELOW_THRESHOLD")
    if any(day["selectedDelta"] > -threshold + 1e-10 for day in day_train):
        reasons.append("NOT_EVERY_TRAINING_DAY_IMPROVES_MATERIALLY")
    if (guard["passed"] is not (not reasons)
            or guard["reasons"] != reasons
            or conservative != (winner if not reasons else "canonical_lp")):
        raise ValueError("Guard was not locked from training-only evidence")

    day_test = _days(raw["holdoutDailyDiagnostics"], test, DAILY_TEST,
                     winner, conservative, "holdout")
    test_scores = _scores(raw["holdoutMaeMwByPolicy"], "holdout aggregate")
    for key in POLICIES:
        _same(test_scores[key], _average(day_test, key), "holdout aggregate")

    direct_values = {
        "trainingSelectedVsCanonicalDeltaMaeMw": margin,
        "holdoutSelectedVsCanonicalDeltaMaeMw": (
            test_scores[winner] - test_scores["canonical_lp"]
        ),
        "trainingConservativeComparatorMaeMw": train_scores[conservative],
        "holdoutConservativeComparatorMaeMw": test_scores[conservative],
        "trainingConservativeVsCanonicalDeltaMaeMw": (
            train_scores[conservative] - train_scores["canonical_lp"]
        ),
        "holdoutConservativeVsCanonicalDeltaMaeMw": (
            test_scores[conservative] - test_scores["canonical_lp"]
        ),
        "largestHoldoutDeteriorationMaeMw": max(
            0.0, *(day["selectedDelta"] for day in day_test)
        ),
        "largestHoldoutConservativeDeteriorationMaeMw": max(
            0.0, *(day["guardedDelta"] for day in day_test)
        ),
    }
    for field, expected in direct_values.items():
        value = raw[field]
        if type(value) not in (int, float) or not isfinite(value):
            raise ValueError(f"{field}: invalid numeric result")
        _same(expected, float(value), field)
    counts = {
        "trainingSelectedDaysBetterThanCanonical": sum(
            day["selectedDelta"] < -1e-8 for day in day_train
        ),
        "holdoutSelectedDaysBetterThanCanonical": sum(
            day["selectedDelta"] < -1e-8 for day in day_test
        ),
        "holdoutConservativeDaysBetterThanCanonical": sum(
            day["guardedDelta"] < -1e-8 for day in day_test
        ),
    }
    for field, expected in counts.items():
        if type(raw[field]) is not int or raw[field] != expected:
            raise ValueError(f"{field}: inconsistent daily results")
    if (type(raw["holdoutDatesReusingTrainingBidCurves"]) is not int
            or raw["holdoutDatesReusingTrainingBidCurves"] != sum(
                day["identicalOfferCurveSeenInTraining"] is True
                for day in raw["holdoutDailyDiagnostics"]
            )):
        raise ValueError("Holdout offer-curve reuse count inconsistent")
    if (raw["holdoutRobustnessAssessment"] != (
        "ONLY_ONE_HOLDOUT_DATE_NO_STATISTICAL_CONFIDENCE" if len(test) == 1
        else "DESCRIPTIVE_MULTIDAY_HOLDOUT_NO_STATISTICAL_CONFIDENCE"
    )):
        raise ValueError("Invalid statistical limitation disclaimer")

    worst = direct_values["largestHoldoutConservativeDeteriorationMaeMw"]
    if not guard["passed"]:
        status = "TRAINING_GUARD_BLOCKED"
    elif worst > 1e-8:
        status = "HOLDOUT_DETERIORATION_OBSERVED"
    else:
        status = "DESCRIPTIVE_ONLY_INSUFFICIENT_EXTERNAL_VALIDATION"

    return {
        "status": status,
        "researchOnly": True,
        "historicalOriginalBidsOnly": True,
        "sourceAuthenticatedByThisReport": False,
        "liveBidAllowed": False,
        "pmssCounterfactualValidated": False,
        "profitForecastValidated": False,
        "trainingDates": train,
        "holdoutDates": test,
        "trainingWinner": winner,
        "trainingGuardPassed": guard["passed"],
        "trainingGuardReasons": reasons,
        "lockedConservativeComparator": conservative,
        "trainingWinnerHoldoutMaeMw": test_scores[winner],
        "canonicalHoldoutMaeMw": test_scores["canonical_lp"],
        "conservativeHoldoutMaeMw": test_scores[conservative],
        "trainingWinnerHoldoutDeltaMaeMw": direct_values[
            "holdoutSelectedVsCanonicalDeltaMaeMw"
        ],
        "conservativeHoldoutDeltaMaeMw": direct_values[
            "holdoutConservativeVsCanonicalDeltaMaeMw"
        ],
        "conservativeWorstSingleDayDeteriorationMaeMw": worst,
        "holdoutDatesReusingTrainingOffers": raw[
            "holdoutDatesReusingTrainingBidCurves"
        ],
        "distinctTrainingBidCurves": distinct_train,
        "holdoutDayCount": len(test),
        "statisticalConfidenceEstablished": False,
        "disclaimer": (
            "Self-consistent anonymous historical ORIGINAL-bid aggregates "
            "are not authenticated PMSS data, independent new-bid validation, "
            "or proof of the real market tie-break or profit. "
            "No live PMSS use is authorized."
        ),
    }
