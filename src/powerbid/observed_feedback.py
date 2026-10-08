"""Strict read-only diagnostics for already-observed PMSS 24h unit results.

Never conflate *historical* market outcomes with forecasts, model counterfactuals,
or economic profit. PMSS 'income' is preserved in its reported units.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

from powerbid.unit_commitment import FeasibilityAudit, TerminalMode, ThermalConstraints, audit_dispatch


@dataclass(frozen=True, slots=True)
class ObservedUnitDay:
    unit_id: str
    market_type: str
    accepted_mw: tuple[float | None, ...]
    reported_price: tuple[float | None, ...]
    reported_income: tuple[float | None, ...]
    observed_energy_mwh: float
    observed_income_raw: float
    nonmissing_power_hours: int
    nonmissing_income_hours: int


def _series(raw: Any, label: str) -> tuple[float | None, ...]:
    if isinstance(raw, Mapping):
        raw = raw.get("datas")
    if not isinstance(raw, (list, tuple)) or len(raw) != 24:
        raise ValueError(f"Observed {label} must contain exactly 24 entries")
    values: list[float | None] = []
    for index, value in enumerate(raw):
        if value is None:
            values.append(None)
            continue
        if isinstance(value, dict):
            value = next((value[k] for k in ("value", "val", "data", "y") if k in value), None)
        if isinstance(value, bool):
            raise ValueError(f"{label}[{index}] must be numeric")
        try:
            number = float(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{label}[{index}] must be numeric") from exc
        if not isfinite(number):
            raise ValueError(f"{label}[{index}] must be finite")
        values.append(number)
    return tuple(values)


def observed_unit_day(
    results: Mapping[str, Any],
    *,
    unit_id: str,
    market_type: str = "DA",
) -> ObservedUnitDay:
    if market_type not in ("DA", "RT"):
        raise ValueError("market_type must be DA or RT")
    if results.get("marketTypeAtom") not in (None, market_type):
        raise ValueError("Result payload market_type does not match requested market")
    if int(results.get("periodNum", 24)) != 24:
        raise ValueError("Expected PMSS 24-hour observed results")
    rows = results.get("unitResults")
    if not isinstance(rows, list):
        raise ValueError("No observed unitResults in PMSS snapshot")
    matches = [
        row for row in rows
        if isinstance(row, dict)
        and str(row.get("unit_id") or row.get("elementId")) == unit_id
        and str(row.get("market_type") or row.get("marketTypeAtom")) == market_type
    ]
    if len(matches) != 1:
        raise ValueError("Expected exactly one observed unit result for selected unit and market")
    row = matches[0]
    power = _series(row.get("accepted_mw", row.get("power")), "accepted MW")
    price = _series(row.get("clearing_prices", row.get("price")), "clearing price")
    income = _series(row.get("income"), "income")
    if any(x is not None and x < 0 for x in power):
        raise ValueError("Observed accepted power must not be negative")
    return ObservedUnitDay(
        unit_id=unit_id,
        market_type=market_type,
        accepted_mw=power,
        reported_price=price,
        reported_income=income,
        observed_energy_mwh=sum(x for x in power if x is not None),
        observed_income_raw=sum(x for x in income if x is not None),
        nonmissing_power_hours=sum(x is not None for x in power),
        nonmissing_income_hours=sum(x is not None for x in income),
    )


def audit_observed_dispatch(
    observed: ObservedUnitDay,
    technical: ThermalConstraints,
    *,
    terminal_mode: TerminalMode = "carryover",
) -> FeasibilityAudit:
    """Do NOT treat missing historical MW as zero dispatch."""
    if observed.unit_id != technical.unit_id:
        raise ValueError("Observed and technical unit IDs differ")
    if any(x is None for x in observed.accepted_mw):
        raise ValueError("Observed dispatch contains unknown hourly values")
    return audit_dispatch(
        technical,
        [float(x) for x in observed.accepted_mw if x is not None],
        terminal_mode=terminal_mode,
    )
