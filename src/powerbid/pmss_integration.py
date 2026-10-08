"""Read-only PMSS data normalization; no authentication or platform writes.

Snapshot shape intentionally separates observed PMSS unit/bid data from a
user-supplied 24-hour demand forecast. Market-result loads are *ex-post*
observations and must not silently stand in for a forecast.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True, slots=True)
class GeneratorSpec:
    unit_id: str
    name: str
    capacity_mw: float
    min_power_mw: float
    running_cost: float
    unit_type: str


@dataclass(frozen=True, slots=True)
class BidSegment:
    start_power: float
    end_power: float
    price: float

    @property
    def quantity_mw(self) -> float:
        return self.end_power - self.start_power


@dataclass(frozen=True, slots=True)
class PeriodBid:
    start_period: int
    end_period: int
    segments: tuple[BidSegment, ...]


@dataclass(frozen=True, slots=True)
class MarketLimits:
    market_type: str
    max_segments: int
    price_floor: float | None
    price_ceiling: float | None
    same_curve: bool

    @classmethod
    def from_pmss(cls, market_system: Mapping[str, Any], market_type: str = "DA") -> MarketLimits:
        rule = next(
            (r for r in market_system.get("spotList", [])
             if r.get("marketAtomType") == market_type),
            None,
        )
        if rule is None:
            raise ValueError(f"Missing PMSS market rules for {market_type}")
        return cls(
            market_type=market_type,
            max_segments=int(rule["unitPowerDeclareSegmentConstraint"]),
            price_floor=_optional_number(rule.get("priceLowerConstraint")),
            price_ceiling=_optional_number(rule.get("priceUpperConstraint")),
            same_curve=str(rule.get("useSameBiddingCurve", 0)) in {"1", "True", "true"},
        )


@dataclass(frozen=True, slots=True)
class PMSSSnapshot:
    """Portable, credential-free, read-only input for 24-hour local analysis."""

    units: tuple[GeneratorSpec, ...]
    bids: dict[str, tuple[PeriodBid, ...]]
    demand_forecast_mw: tuple[float, ...]
    forecast_source: str
    limits: MarketLimits
    period_num: int = 24

    def __post_init__(self) -> None:
        if self.period_num != 24:
            raise ValueError("PMSS DA snapshot currently requires 24 periods")
        if len(self.demand_forecast_mw) != self.period_num:
            raise ValueError("Provide an explicit demand forecast for all 24 periods")
        if not self.forecast_source.strip():
            raise ValueError("forecastSource must identify the source of forecast inputs")
        if len({u.unit_id for u in self.units}) != len(self.units):
            raise ValueError("Duplicate generator IDs")
        if set(self.bids) != {u.unit_id for u in self.units}:
            raise ValueError("Each unit must have a PMSS bidding curve")
        for unit in self.units:
            for period in range(1, self.period_num + 1):
                curve_for_period(self.bids[unit.unit_id], period)

    def unit(self, unit_id: str) -> GeneratorSpec:
        return next(unit for unit in self.units if unit.unit_id == unit_id)


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return _number(value, "rule bound")


def flatten_pmss_units(tree: list[dict[str, Any]]) -> tuple[GeneratorSpec, ...]:
    """Map actual unit-tree leaves; prefer adjustable MW over MVA rating."""
    result: list[GeneratorSpec] = []
    def visit(nodes: list[dict[str, Any]]) -> None:
        for item in nodes:
            if item.get("leaf"):
                ident = str(item.get("unitId") or item.get("key") or "")
                if not ident:
                    raise ValueError("PMSS unit tree leaf has no ID")
                max_mw = _optional_number(item.get("pdAdjustMax"))
                if max_mw is None or max_mw <= 0:
                    max_mw = _number(item.get("mvarate"), "mvarate")
                minimum = _optional_number(item.get("pdAdjustMin")) or 0.0
                cost = _number(item.get("runningCost"), "runningCost")
                if max_mw <= 0 or minimum < 0 or minimum > max_mw:
                    raise ValueError(f"Invalid power limits for {ident}")
                result.append(
                    GeneratorSpec(
                        unit_id=ident,
                        name=str(item.get("title") or item.get("name") or ident),
                        capacity_mw=max_mw,
                        min_power_mw=minimum,
                        running_cost=cost,
                        unit_type=str(item.get("unitType") or "unknown"),
                    )
                )
            else:
                visit(item.get("children") or [])
    visit(tree)
    if not result:
        raise ValueError("No generator leaves found in PMSS unit tree")
    return tuple(result)


def parse_period_bids(bid_payload: Mapping[str, Any]) -> tuple[PeriodBid, ...]:
    """Preserve the actual start/end periods and cumulative MW boundaries."""
    periods: list[PeriodBid] = []
    for period in bid_payload.get("datas") or []:
        segments = tuple(
            BidSegment(
                _number(s["startPower"], "startPower"),
                _number(s["endPower"], "endPower"),
                _number(s["price"], "price"),
            )
            for s in sorted(period.get("segmentDatas") or [], key=lambda s: int(s["segmentOrder"]))
        )
        if not segments or len(segments) > 5:
            raise ValueError("PMSS curve must have one to five segments")
        last = None
        for segment in segments:
            if segment.start_power < 0 or segment.end_power <= segment.start_power:
                raise ValueError("Invalid PMSS segment capacity")
            if last is not None and abs(segment.start_power - last) > 1e-7:
                raise ValueError("Non-contiguous PMSS capacity segments")
            last = segment.end_power
        start, end = int(period["startPeriod"]), int(period["endPeriod"])
        if not 1 <= start <= end <= 24:
            raise ValueError("Invalid PMSS period range")
        periods.append(PeriodBid(start, end, segments))
    if not periods:
        raise ValueError("Missing PMSS period curves")
    return tuple(periods)


def curve_for_period(period_bids: tuple[PeriodBid, ...], period: int) -> tuple[BidSegment, ...]:
    matches = [b.segments for b in period_bids if b.start_period <= period <= b.end_period]
    if len(matches) != 1:
        raise ValueError(f"Period {period} has {len(matches)} matching bid curves (expected 1)")
    return matches[0]


def snapshot_from_pmss(
    *,
    unit_tree: list[dict[str, Any]],
    unit_bids: Mapping[str, Mapping[str, Any]],
    market_system: Mapping[str, Any],
    demand_forecast_mw: list[float],
    forecast_source: str,
    market_type: str = "DA",
) -> PMSSSnapshot:
    units = flatten_pmss_units(unit_tree)
    bids = {u.unit_id: parse_period_bids(unit_bids[u.unit_id]) for u in units}
    loads = tuple(_number(v, "demand forecast") for v in demand_forecast_mw)
    if any(v < 0 for v in loads):
        raise ValueError("Demand forecast must be non-negative")
    return PMSSSnapshot(
        units=units,
        bids=bids,
        demand_forecast_mw=loads,
        forecast_source=forecast_source,
        limits=MarketLimits.from_pmss(market_system, market_type),
    )


@dataclass(frozen=True, slots=True)
class UnitClearingRow:
    unit_id: str
    name: str
    market_type: str
    accepted_mw: tuple[float | None, ...]
    clearing_prices: tuple[float | None, ...]
    income: tuple[float | None, ...]


def read_24_values(
    series: Mapping[str, Any], field_name: str, periods: int = 24
) -> tuple[float | None, ...]:
    """Decode hourly series without using misleading 'sum'/'average' summaries."""
    values = series.get("datas")
    if not isinstance(values, list) or len(values) != periods:
        raise ValueError(f"{field_name}: expected {periods} hourly points")
    result: list[float | None] = []
    for i, value in enumerate(values):
        if isinstance(value, dict):
            for key in ("value", "val", "data", "y"):
                if key in value:
                    value = value[key]
                    break
            else:
                raise ValueError(f"{field_name}[{i}] uses an unsupported point schema")
        result.append(None if value is None else _number(value, f"{field_name}[{i}]"))
    return tuple(result)


def parse_unit_clearing(payload: Mapping[str, Any]) -> tuple[UnitClearingRow, ...]:
    """Normalize confirmed listForGd response: periodNum/datas[power,price,income]."""
    count = int(payload.get("periodNum", 24))
    if count != 24:
        raise ValueError(f"Unsupported PMSS period count: {count}")
    rows: list[UnitClearingRow] = []
    for row in payload.get("datas") or []:
        rows.append(
            UnitClearingRow(
                unit_id=str(row["elementId"]),
                name=str(row["elementName"]),
                market_type=str(row["marketTypeAtom"]),
                accepted_mw=read_24_values(row["power"], "power"),
                clearing_prices=read_24_values(row["price"], "price"),
                income=read_24_values(row["income"], "income"),
            )
        )
    return tuple(rows)


def selected_leaf_ids(tree: list[dict[str, Any]], market_type: str) -> list[str]:
    """Select element IDs from the matching DA/RT parent, never from another Tab.

    PMSS returns two market groups; do not assume RT IDs equal DA IDs.
    """
    def marker(node: Mapping[str, Any]) -> str:
        keys = ("key", "value", "title", "marketTypeAtom")
        return " ".join(str(node.get(k, "")) for k in keys).lower()
    if market_type not in {"DA", "RT"}:
        raise ValueError("market_type must be DA or RT")
    tags = ("da", "日前") if market_type == "DA" else ("rt", "实时")
    parents = [item for item in tree if any(tag in marker(item) for tag in tags)]
    if len(parents) != 1:
        raise ValueError(f"Could not uniquely identify PMSS {market_type} result tree group")
    ids: list[str] = []
    def visit(items: list[dict[str, Any]]) -> None:
        for item in items:
            children = item.get("children") or []
            if children:
                visit(children)
            elif item.get("leaf"):
                ident = item.get("key") or item.get("value")
                if ident is not None:
                    ids.append(str(ident))
    visit(parents[0].get("children") or [])
    return ids
