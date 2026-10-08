"""Local five-block price/quantity optimizer backed by existing uniform-price engine.

This is deliberately a *surrogate* single-zone simulation, NOT a PMSS clearing
result. No network access, no bidding submission, and no run-clearing operation.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

from powerbid.clearing.uniform_price import UniformPriceClearingEngine
from powerbid.models import MarketScenario, Offer
from powerbid.pmss_integration import BidSegment, PMSSSnapshot, curve_for_period


@dataclass(frozen=True, slots=True)
class HourlyTrial:
    period: int
    demand_mw: float
    clearing_price: float | None
    target_accepted_mw: float
    target_profit: float
    feasible: bool


@dataclass(frozen=True, slots=True)
class CurveEvaluation:
    segments: tuple[BidSegment, ...]
    total_profit: float
    worst_hour_profit: float
    total_accepted_mwh: float
    hours: tuple[HourlyTrial, ...]


@dataclass(frozen=True, slots=True)
class SegmentedOptimization:
    """Baseline is historical PMSS data; recommendation is read-only simulation."""
    target_unit_id: str
    baseline: CurveEvaluation
    recommended: CurveEvaluation
    evaluated_curves: int
    algorithm: str = "local coordinate search / single-zone uniform price"


def validate_curve(segments: Sequence[BidSegment], max_segments: int = 5) -> None:
    if not 1 <= len(segments) <= max_segments:
        raise ValueError(f"Expected 1..{max_segments} bid segments")
    previous = None
    for block in segments:
        if any(not isfinite(v) for v in (block.start_power, block.end_power, block.price)):
            raise ValueError("Non-finite segment number")
        if block.start_power < 0 or block.end_power <= block.start_power:
            raise ValueError("Invalid segment power range")
        if previous is not None and abs(previous - block.start_power) > 1e-7:
            raise ValueError("Gap or overlap between bid segments")
        previous = block.end_power


def evaluate_curve(
    snapshot: PMSSSnapshot,
    target_unit_id: str,
    segments: Sequence[BidSegment],
) -> CurveEvaluation:
    """Reclear 24 hourly scenarios with all peer PMSS *submitted* curves.

    Simplifications: uniform-price single zone; no start/ramp/min up/down,
    reserve constraints, network, LMP, or PMSS engine calls.
    """
    validate_curve(segments, snapshot.limits.max_segments)
    if target_unit_id not in snapshot.bids:
        raise ValueError(f"Unknown target unit: {target_unit_id}")
    target = snapshot.unit(target_unit_id)
    if segments[-1].end_power > target.capacity_mw + 1e-7:
        raise ValueError("Target curve exceeds recorded adjustable unit capacity")
    if not snapshot.limits.same_curve:
        raise ValueError("Current shared 24h curve optimizer needs useSameBiddingCurve=1")
    market_engine = UniformPriceClearingEngine()
    rows: list[HourlyTrial] = []
    target_parts = [f"{target_unit_id}::seg{i}" for i in range(1, len(segments) + 1)]
    for period, demand in enumerate(snapshot.demand_forecast_mw, start=1):
        offers: list[Offer] = []
        for unit in snapshot.units:
            blocks = segments if unit.unit_id == target_unit_id else curve_for_period(
                snapshot.bids[unit.unit_id], period
            )
            for i, block in enumerate(blocks, start=1):
                offers.append(
                    Offer(
                        unit_id=f"{unit.unit_id}::seg{i}",
                        quantity_mw=block.quantity_mw,
                        bid_price=block.price,
                        marginal_cost=unit.running_cost,
                    )
                )
        scenario = MarketScenario(
            name=f"PMSS read-only surrogate / period {period}",
            demand_mw=demand,
            interval_hours=1,
            target_unit_id=target_parts[0],
            offers=tuple(offers),
            data_source="mixed_platform_bids_and_forecast",
        )
        clearing = market_engine.clear(scenario)
        accepted = sum(clearing.accepted_mw.get(key, 0.0) for key in target_parts)
        price = clearing.clearing_price
        profit = (0.0 if price is None else (price - target.running_cost) * accepted)
        rows.append(
            HourlyTrial(period, demand, price, accepted, profit, clearing.feasible)
        )
    if not all(row.feasible for row in rows):
        raise ValueError("Some hourly demand forecasts exceed available offers")
    return CurveEvaluation(
        segments=tuple(segments),
        total_profit=sum(r.target_profit for r in rows),
        worst_hour_profit=min(r.target_profit for r in rows),
        total_accepted_mwh=sum(r.target_accepted_mw for r in rows),
        hours=tuple(rows),
    )


def _equal_buckets(capacity: float, n: int, price: float) -> tuple[BidSegment, ...]:
    ends = [round(capacity * k / n, 8) for k in range(n + 1)]
    return tuple(BidSegment(ends[i], ends[i + 1], price) for i in range(n))


def _with_price(
    blocks: tuple[BidSegment, ...], index: int, price: float
) -> tuple[BidSegment, ...]:
    out = list(blocks)
    b = out[index]
    out[index] = BidSegment(b.start_power, b.end_power, price)
    return tuple(out)


def _with_boundary(
    blocks: tuple[BidSegment, ...], index: int, boundary: float
) -> tuple[BidSegment, ...]:
    """Move cumulative MW boundary between blocks index and index+1."""
    out = list(blocks)
    left, right = out[index], out[index + 1]
    out[index] = BidSegment(left.start_power, boundary, left.price)
    out[index + 1] = BidSegment(boundary, right.end_power, right.price)
    return tuple(out)


def optimize_segmented_bid(
    snapshot: PMSSSnapshot,
    target_unit_id: str,
    candidate_prices: Sequence[float],
    *,
    quantity_step_mw: float | None = None,
    iterations: int = 3,
) -> SegmentedOptimization:
    """Coordinate search jointly over five block prices and four MW boundaries.

    The last MW boundary is fixed at the observed capacity. Input prices are
    explicit user-selected *candidate* values; platform price bounds are
    advisory until webpage validation and course rules are verified.
    """
    if iterations < 1 or iterations > 30:
        raise ValueError("iterations must be between 1 and 30")
    prices = sorted(set(float(v) for v in candidate_prices))
    if not prices or any(not isfinite(v) or v < 0 for v in prices):
        raise ValueError("Candidate bid prices must be finite and non-negative")
    if not snapshot.limits.same_curve:
        raise ValueError("PMSS DA useSameBiddingCurve must equal 1")
    baseline_segments = curve_for_period(snapshot.bids[target_unit_id], 1)
    for hour in range(2, 25):
        if curve_for_period(snapshot.bids[target_unit_id], hour) != baseline_segments:
            raise ValueError(
                "Target has different hourly curves; shared-curve optimizer not applicable"
            )
    baseline = evaluate_curve(snapshot, target_unit_id, baseline_segments)
    capacity = baseline_segments[-1].end_power
    n = min(5, snapshot.limits.max_segments)
    if n < 1 or capacity <= 0:
        raise ValueError("Invalid unit capacity/segment count")
    if quantity_step_mw is None:
        quantity_step_mw = capacity / 20
    if not 0 < quantity_step_mw < capacity:
        raise ValueError("quantity_step_mw must be between 0 and max capacity")
    initial = _equal_buckets(capacity, n, prices[0])
    best = evaluate_curve(snapshot, target_unit_id, initial)
    evaluations = 2  # baseline + seed
    # A flat price curve is a useful reference for each candidate and avoids
    # an unnecessary local-search disadvantage versus a one-block baseline.
    for price in prices[1:]:
        trial = evaluate_curve(snapshot, target_unit_id, _equal_buckets(capacity, n, price))
        evaluations += 1
        if trial.total_profit > best.total_profit + 1e-8:
            best = trial
    tol = 1e-8

    def consider(curve: tuple[BidSegment, ...]) -> None:
        nonlocal best, evaluations
        evaluation = evaluate_curve(snapshot, target_unit_id, curve)
        evaluations += 1
        if evaluation.total_profit > best.total_profit + tol:
            best = evaluation

    for _ in range(iterations):
        before = best.total_profit
        for i in range(n - 1, -1, -1):
            for candidate in prices:
                # For a standard nondecreasing cumulative supply curve.
                if i > 0 and candidate < best.segments[i - 1].price:
                    continue
                if i + 1 < n and candidate > best.segments[i + 1].price:
                    continue
                if abs(candidate - best.segments[i].price) <= tol:
                    continue
                consider(_with_price(best.segments, i, candidate))
        # Quantities are optimized as cumulative MW breakpoints.
        min_width = max(1e-7, capacity * 1e-6)
        for i in range(n - 1):
            for delta in (-quantity_step_mw, quantity_step_mw):
                left, right = best.segments[i], best.segments[i + 1]
                boundary = round(left.end_power + delta, 8)
                if not left.start_power + min_width < boundary < right.end_power - min_width:
                    continue
                consider(_with_boundary(best.segments, i, boundary))
        if best.total_profit <= before + tol:
            break
    return SegmentedOptimization(
        target_unit_id=target_unit_id,
        baseline=baseline,
        recommended=best,
        evaluated_curves=evaluations,
    )


def build_pmss_dry_run_payload(
    *,
    scope_id: str,
    unit_id: str,
    segments: Sequence[BidSegment],
    period_num: int = 24,
    existing_bid: Mapping[str, Any],
) -> dict[str, object]:
    """Prepare JSON for review; preserve original PMSS cost fields, never HTTP."""
    validate_curve(segments)
    cost_fields = ("minTechPowerCost", "startCostHot", "startCostWarm", "startCostCold")
    if any(key not in existing_bid for key in cost_fields):
        raise ValueError("Existing PMSS bid must supply all four cost fields")
    return {
        "scopeId": scope_id,
        "minTechPowerCost": existing_bid["minTechPowerCost"],
        "startCostHot": existing_bid["startCostHot"],
        "startCostWarm": existing_bid["startCostWarm"],
        "startCostCold": existing_bid["startCostCold"],
        "unitId": unit_id,
        "datas": [{
            "startPeriod": 1,
            "endPeriod": period_num,
            "segmentDatas": [
                {
                    "startPower": s.start_power,
                    "endPower": s.end_power,
                    "price": s.price,
                    "segmentOrder": i,
                }
                for i, s in enumerate(segments, start=1)
            ],
        }],
    }
