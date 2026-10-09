"""PMSS market-rule safeguards for NEW local bid recommendations.

Saved PMSS historical bids are immutable evidence, even if they conflict
with the market limits currently embedded in a snapshot. Their presence
does not grant permission to generate new bids outside those limits.

No network access and no PMSS write/execute methods appear here.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from math import isfinite

from powerbid.pmss_integration import BidSegment, PMSSSnapshot
from powerbid.pmss_strategy import validate_curve


@dataclass(frozen=True)
class HistoricPriceRuleAudit:
    price_floor: float | None
    price_ceiling: float | None
    original_units_outside_current_range: int
    original_segments_outside_current_range: int
    largest_original_price: float
    affected_unit_names: tuple[str, ...]
    interpretation: str = (
        "Historical saved bids versus the currently loaded market rule; "
        "does NOT prove a historical rule violation or permit new out-of-range bids"
    )


def _outside(price: float, floor: float | None, ceiling: float | None) -> bool:
    return ((floor is not None and price < floor) or
            (ceiling is not None and price > ceiling))


def audit_saved_bid_price_limits(snapshot: PMSSSnapshot) -> HistoricPriceRuleAudit:
    offending = set()
    n_offending = 0
    greatest = float("-inf")
    for unit in snapshot.units:
        for period in snapshot.bids[unit.unit_id]:
            for block in period.segments:
                greatest = max(greatest, block.price)
                if _outside(
                    block.price, snapshot.limits.price_floor,
                    snapshot.limits.price_ceiling,
                ):
                    offending.add(unit.unit_id)
                    n_offending += 1
    return HistoricPriceRuleAudit(
        price_floor=snapshot.limits.price_floor,
        price_ceiling=snapshot.limits.price_ceiling,
        original_units_outside_current_range=len(offending),
        original_segments_outside_current_range=n_offending,
        largest_original_price=greatest,
        affected_unit_names=tuple(
            unit.name for unit in snapshot.units if unit.unit_id in offending
        ),
    )


def validate_new_bid_prices(
    snapshot: PMSSSnapshot,
    prices: Sequence[float],
) -> None:
    if not prices:
        raise ValueError("Candidate price list is empty")
    for raw in prices:
        if isinstance(raw, bool) or not isfinite(raw):
            raise ValueError("Candidate bid price must be finite")
        if raw < 0 or raw > 10_000:
            raise ValueError("Candidate bid price outside online analysis safety range")
        if _outside(raw, snapshot.limits.price_floor, snapshot.limits.price_ceiling):
            raise ValueError(
                f"Candidate price {raw:g} outside current PMSS market rule "
                f"[{snapshot.limits.price_floor}, {snapshot.limits.price_ceiling}]. "
                "Saved historical bids are not an exemption."
            )


def validate_new_curve(
    snapshot: PMSSSnapshot,
    target_unit_id: str,
    segments: Sequence[BidSegment],
) -> None:
    validate_curve(segments, snapshot.limits.max_segments)
    validate_new_bid_prices(snapshot, [block.price for block in segments])
    target = snapshot.unit(target_unit_id)
    if segments[-1].end_power > target.capacity_mw + 1e-7:
        raise ValueError("New bid exceeds verified target unit capacity")


def summarize_bid_rule_audit(snapshot: PMSSSnapshot) -> dict:
    return asdict(audit_saved_bid_price_limits(snapshot))
