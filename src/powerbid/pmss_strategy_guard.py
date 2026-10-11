"""Independent-date, fail-closed PMSS strategy research admission.

A submitted candidate is *recomputed*, never trusted to supply its own score,
margin or PMSS outcomes. Original historical bids alone have observed PMSS
results; a changed bid has NO PMSS counterfactual result in those snapshots.
This module has no network I/O, PMSS write path or platform clearing operation.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from math import isfinite
from typing import Any

from powerbid.historical_validation import (
    ValidationPolicy,
    judge_historical_model,
    validate_historical_day,
)
from powerbid.network_dispatch import network_from_dict
from powerbid.network_strategy import evaluate_network_plan, verify_network_inputs
from powerbid.pmss_bid_rule_safety import validate_new_curve
from powerbid.pmss_integration import BidSegment, PeriodBid, snapshot_from_pmss
from powerbid.strategy_lab import DemandStress

# Conservative course-project tolerances, NOT teacher-market official criteria.
DEFAULT_DISPATCH_MAE_MW = 20.0
DEFAULT_NODAL_PRICE_MAE = 50.0
_MAX_CASES = 5
_MAX_CANDIDATES = 6
_SCENARIO = (DemandStress(
    name="historical_inputs_local_dc_only",
    demand_factor=1.0, peer_price_factor=1.0, probability=1.0,
),)


def _number(value: Any, label: str) -> float:
    if type(value) not in (float, int) or not isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _snapshot(raw: Mapping[str, Any]):
    return snapshot_from_pmss(
        unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )


def _dated_cases(cases: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if isinstance(cases, (str, bytes)) or not 3 <= len(cases) <= _MAX_CASES:
        raise ValueError("Require 3..5 distinct dated historical PMSS cases")
    indexed = {}
    for raw in cases:
        if not isinstance(raw, Mapping) or raw.get("historicalBacktestOnly") is not True:
            raise ValueError("Only historical read-only case objects are supported")
        label = raw.get("caseDate")
        if type(label) is not str:
            raise ValueError("Missing caseDate")
        try:
            if date.fromisoformat(label).isoformat() != label:
                raise ValueError("Noncanonical caseDate")
        except ValueError as exc:
            raise ValueError("caseDate must be YYYY-MM-DD") from exc
        if label in indexed:
            raise ValueError("Duplicate caseDate is not independent evidence")
        indexed[label] = raw
    return [indexed[key] for key in sorted(indexed)]


def _offer_digest(snapshot: Any) -> str:
    """Hash normalized bid curves, never scope IDs, metadata or case dates."""
    curves = {
        unit: [
            [period.start_period, period.end_period, [
                [block.start_power, block.end_power, block.price]
                for block in period.segments
            ]]
            for period in periods
        ]
        for unit, periods in sorted(snapshot.bids.items())
    }
    encoded = json.dumps(curves, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _curve(raw: Mapping[str, Any]) -> tuple[BidSegment, ...]:
    # Compatible with the existing /network-rank price_blocks contract and
    # with Window A candidates using segments/recommended_segments.
    blocks = raw.get("price_blocks")
    if blocks is None:
        blocks = raw.get("segments", raw.get("recommended_segments"))
    if not isinstance(blocks, (list, tuple)) or not 1 <= len(blocks) <= 5:
        raise ValueError("Candidate requires 1..5 price_blocks or segments")
    result = []
    for index, block in enumerate(blocks):
        if isinstance(block, Mapping):
            values = (block.get("start_power"), block.get("end_power"),
                      block.get("price"))
        elif isinstance(block, (list, tuple)) and len(block) == 3:
            values = block
        else:
            raise ValueError(f"Malformed bid block {index + 1}")
        a, b, p = (
            _number(value, f"candidate block {index + 1}") for value in values
        )
        result.append(BidSegment(a, b, p))
    return tuple(result)


def _candidate(raw: Mapping[str, Any]) -> tuple[str, str, tuple[BidSegment, ...]]:
    if not isinstance(raw, Mapping):
        raise ValueError("Candidate must be a JSON object")
    name = raw.get("name", raw.get("label"))
    identifier = raw.get("id", raw.get("strategy_id", name))
    if (type(name) is not str or not 1 <= len(name.strip()) <= 100
            or type(identifier) is not str or not 1 <= len(identifier.strip()) <= 100):
        raise ValueError("Candidate requires a short name and string ID")
    return identifier, name, _curve(raw)


def _scaled(value: float, values: list[float]) -> float:
    low, high = min(values), max(values)
    if high - low <= 1e-8 * max(1.0, abs(low), abs(high)):
        return 0.0  # No spurious advantage for tied/huge simulated margins.
    return max(0.0, min(1.0, (value - low) / (high - low)))


def assess_pmss_strategy_candidates(
    cases: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    target_unit_id: str,
    *,
    max_dispatch_mae_mw: float = DEFAULT_DISPATCH_MAE_MW,
    max_nodal_price_mae: float = DEFAULT_NODAL_PRICE_MAE,
) -> dict[str, Any]:
    """Recompute ORIGINAL-bid error and hypothetical bid risk on separate days.

    Scores and ordering use ONLY training dates; holdout is evaluated after the
    ranking is fixed. Neither date group contains a teacher-cleared outcome
    for any new bid. Results are diagnostic and never live-bid approval.
    """
    ordered = _dated_cases(cases)
    if type(target_unit_id) is not str or not target_unit_id:
        raise ValueError("Provide target_unit_id")
    if (isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence)
            or not 1 <= len(candidates) <= _MAX_CANDIDATES):
        raise ValueError("Require 1..6 bounded candidate curves")
    dispatch_tol = _number(max_dispatch_mae_mw, "Dispatch MAE tolerance")
    price_tol = _number(max_nodal_price_mae, "Price MAE tolerance")
    if not (0 <= dispatch_tol <= 10000 and 0 <= price_tol <= 100000):
        raise ValueError("Tolerances outside bounded diagnostic ranges")

    specs = [_candidate(candidate) for candidate in candidates]
    ids = [item[0] for item in specs]
    if len(set(ids)) != len(ids):
        raise ValueError("Candidate identifiers must be unique")
    # Bound expensive 24-hour LP replay BEFORE launching any historical solves.
    snapshots = [_snapshot(raw) for raw in ordered]
    networks = [network_from_dict(raw["dcNetwork"]) for raw in ordered]
    if any(
        len(snap.units) > 30 or len(net.buses) > 60 or len(net.lines) > 90
        for snap, net in zip(snapshots, networks, strict=True)
    ):
        raise ValueError("Online DC history exceeds bounded network size")
    days = [validate_historical_day(raw) for raw in ordered]
    if len({day.grid_fingerprint for day in days}) != 1:
        raise ValueError("Cannot pool mismatching DC topology/parameters")
    if len({day.unit_count for day in days}) != 1:
        raise ValueError("Generator count changed between cases")

    capacity = snapshots[0].unit(target_unit_id).capacity_mw
    for snap, net in zip(snapshots, networks, strict=True):
        verify_network_inputs(snap, net, target_unit_id)
        if abs(snap.unit(target_unit_id).capacity_mw - capacity) > 1e-5:
            raise ValueError("Target capacity changed between historical days")

    policy = ValidationPolicy(
        dispatch_tol, price_tol, min_coverage=1.0,
        min_distinct_dates=3, holdout_dates=1,
    )
    historical = judge_historical_model(days, policy)
    offer_hashes = [_offer_digest(snap) for snap in snapshots]
    # Repeated days are different demand observations, NOT independent offer curves.
    holdout_reused_bid = offer_hashes[-1] in set(offer_hashes[:-1])
    training_distinct_bids = len(set(offer_hashes[:-1]))
    baseline_fit = historical.status == "HISTORICAL_BASELINE_WITHIN_TOLERANCE"
    evidence_good = baseline_fit and training_distinct_bids >= 2 and not holdout_reused_bid
    if evidence_good:
        grade = "C2_HISTORICAL_ORIGINAL_BID_FIT_ONLY"
    else:
        grade = "C1_UNVERIFIED_OR_WEAK_HISTORICAL_FIT"

    metrics: list[dict[str, Any]] = []
    for identifier, name, blocks in specs:
        issues: list[str] = []
        warnings: list[str] = []
        if abs(blocks[0].start_power) > 1e-6:
            issues.append("BID_DOES_NOT_START_AT_ZERO")
        if any(a.price > b.price + 1e-8 for a, b in zip(blocks, blocks[1:], strict=False)):
            issues.append("DECREASING_BLOCK_PRICES")
        if all(abs(block.price) <= 1e-9 for block in blocks):
            issues.append("ALL_ZERO_PRICES")
        max_quote = max(block.price for block in blocks)
        limit = snapshots[-1].limits.price_ceiling
        if limit is not None and limit > 0 and max_quote >= 0.95 * limit:
            warnings.append("BID_NEAR_MARKET_PRICE_CEILING")
        if blocks[-1].end_power < 0.8 * capacity - 1e-6:
            warnings.append("BID_OFFERS_LESS_THAN_80_PERCENT_OF_CAPACITY")

        for snap in snapshots:
            try:
                validate_new_curve(snap, target_unit_id, blocks)
            except (ValueError, StopIteration):
                issues.append("CURVE_VIOLATES_CASE_RULES_OR_CAPACITY")
                break

        train_margins: list[float] = []
        diagnostic_holdout_margin: float | None = None
        full_days: list[str] = []
        if not issues:
            plan = (PeriodBid(1, 24, blocks),)
            for index, (snap, net) in enumerate(zip(snapshots, networks, strict=True)):
                try:
                    trial = evaluate_network_plan(
                        snap, net, target_unit_id, name, plan, _SCENARIO
                    )
                except (ValueError, RuntimeError):
                    issues.append("LOCAL_DC_EVALUATION_FAILED")
                    train_margins.clear()
                    diagnostic_holdout_margin = None
                    break
                modeled_day = trial.scenarios[0]
                if all(
                    hour.dispatched_mw >= capacity - max(0.01, capacity * 1e-4)
                    for hour in modeled_day.hours
                ):
                    full_days.append(days[index].case_date)
                if index == len(days) - 1:
                    diagnostic_holdout_margin = modeled_day.total_margin
                else:
                    train_margins.append(modeled_day.total_margin)
            if full_days:
                issues.append("FULL_CAPACITY_EVERY_HOUR_IN_LOCAL_SIMULATION")
        if train_margins and any(v < 0 for v in train_margins):
            warnings.append("NEGATIVE_LOCAL_MARGIN_ON_TRAINING_DAY")
        metrics.append({
            "id": identifier, "name": name,
            "issues": sorted(set(issues)), "warnings": sorted(set(warnings)),
            "training_margins": train_margins,
            "holdout_margin": diagnostic_holdout_margin,
            "full_days": full_days, "blocks": blocks,
        })

    # Fail-closed comparison: invalid bids cannot gain ranking weight from
    # bogus/unbounded caller-supplied scores.
    valid = [row for row in metrics if len(row["training_margins"]) == len(days)-1
             and not row["issues"]]
    averages = [sum(row["training_margins"])/len(row["training_margins"]) for row in valid]
    worsts = [min(row["training_margins"]) for row in valid]
    rankings = []
    for row in metrics:
        margins = row["training_margins"]
        score: float | None = None
        if row in valid:
            mean_margin = sum(margins)/len(margins)
            worst_margin = min(margins)
            variation = max(margins) - min(margins)
            stability = max(0.0, 1.0 - min(1.0, variation / (
                abs(mean_margin) + abs(worst_margin) + 1.0
            )))
            safety = 0.5 if "BID_NEAR_MARKET_PRICE_CEILING" in row["warnings"] else 1.0
            score = round(
                30*_scaled(mean_margin, averages)
                + 25*_scaled(worst_margin, worsts)
                + 25*stability + 20*safety,
                3,
            )
        admitted = score is not None and evidence_good
        rankings.append({
            "candidate_id": row["id"], "candidate_name": row["name"],
            "score_training_only_0_to_100": score,
            "training_modeled_margin_mean": (
                sum(margins)/len(margins) if margins else None
            ),
            "training_modeled_margin_worst": min(margins) if margins else None,
            "holdout_modeled_margin_diagnostic_only": row["holdout_margin"],
            "local_full_output_day_dates": row["full_days"],
            "hard_blockers": row["issues"],
            "risk_warnings": row["warnings"],
            "research_shortlist_admitted": admitted,
            "live_bid_allowed": False,
            "real_pmss_candidate_profit_verified": False,
            "score_provenance": "LOCAL_DC_TRAINING_DATES_ONLY_RELATIVE_SCORE",
        })
    rankings.sort(key=lambda row: (
        row["score_training_only_0_to_100"] is not None,
        row["score_training_only_0_to_100"] or -1,
        row["candidate_id"],
    ), reverse=True)
    # Never suggest a candidate if the baseline itself is unreliable.
    shortlist = [
        row["candidate_id"] for row in rankings
        if row["research_shortlist_admitted"]
    ]
    return {
        "schemaVersion": 1,
        "status": "HISTORICAL_ONLY_LOCAL_STRATEGY_RESEARCH",
        "model_confidence_grade": grade,
        "training_case_dates": [day.case_date for day in days[:-1]],
        "untouched_holdout_case_dates": [days[-1].case_date],
        "original_bid_distinct_training_curves": training_distinct_bids,
        "holdout_reuses_training_original_bid_curve": holdout_reused_bid,
        "historical_original_bid_validation": {
            **asdict(historical),
            "tolerances_are_project_research_preferences_not_pmss_rules": True,
        },
        "per_day_original_bid_simulation_vs_real_pmss": [{
            "case_date": day.case_date,
            "dispatch_mae_mw": day.unit_dispatch.mae,
            "nodal_price_mae_pmss_reported_unit_unverified": day.nodal_price.mae,
            "absolute_line_flow_mae_mw": day.line_flow_abs.mae,
            "dispatch_coverage": day.unit_dispatch.coverage,
            "price_coverage": day.nodal_price.coverage,
            "flow_coverage": day.line_flow_abs.coverage,
        } for day in days],
        "candidates": rankings,
        "research_shortlist_candidate_ids": shortlist,
        "training_ranked_first_candidate_id": rankings[0]["candidate_id"] if (
            rankings and rankings[0]["score_training_only_0_to_100"] is not None
        ) else None,
        "recommended_for_real_pmss": None,
        "full_unit_commitment_physics_verified": False,
        "teacher_new_bid_clearing_verified": False,
        "teacher_result_authenticity_verified_by_upload": False,
        "actual_pmss_counterfactual_profit_available": False,
        "historical_fit_is_new_bid_validation": False,
        "pmss_write_performed": False,
        "pmss_clearing_executed": False,
        "warning": (
            "Original bid errors use observed teacher history. Every modified "
            "candidate margin is a retrospective DC what-if on known inputs; "
            "it is neither a PMSS-cleared result nor audited real net earnings. "
            "Dates and bid-curve reuse limit independence. Unknown start/ramp/"
            "min-up-down/AC/price rules preclude live recommendation."
        ),
    }
