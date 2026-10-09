"""Strict multi-day read-only validation of the original PMSS bids.

Uses the verified DC grid bridge and *original* uploaded PMSS offer curves.
Never treats historical nodal prices as candidate-bid counterfactuals; never
submits PMSS bids or executes PMSS clearing. A single date cannot certify a
strategy for forward-looking use.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from math import isfinite, sqrt
from typing import Any

from powerbid.network_dispatch import DcOffer, dc_clear_hour, network_from_dict
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_diagnostics import series24
from powerbid.pmss_integration import curve_for_period, snapshot_from_pmss


@dataclass(frozen=True, slots=True)
class ErrorMetric:
    mae: float | None
    rmse: float | None
    observed_points: int
    expected_points: int

    @property
    def coverage(self) -> float:
        return self.observed_points / self.expected_points if self.expected_points else 0.0


@dataclass(frozen=True, slots=True)
class UnitError:
    unit_id: str
    dispatch: ErrorMetric


@dataclass(frozen=True, slots=True)
class DayValidation:
    case_date: str
    grid_fingerprint: str
    unit_count: int
    bus_count: int
    branch_count: int
    total_demand_mwh: float
    unit_dispatch: ErrorMetric
    nodal_price: ErrorMetric
    line_flow_abs: ErrorMetric
    per_unit: tuple[UnitError, ...]
    max_hourly_dispatch_mae: float | None
    max_hourly_lmp_mae: float | None
    model_label: str = (
        "historical original-bid read-only DC surrogate, "
        "NOT PMSS validation of new bids"
    )


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    """User-defined acceptance thresholds; these are NOT universal market standards."""

    max_unit_dispatch_mae_mw: float
    max_nodal_price_mae: float
    min_coverage: float = 0.95
    min_distinct_dates: int = 3
    holdout_dates: int = 1

    def __post_init__(self) -> None:
        for value in (self.max_unit_dispatch_mae_mw, self.max_nodal_price_mae):
            if isinstance(value, bool) or not isfinite(value) or value < 0:
                raise ValueError("User thresholds must be finite and nonnegative")
        if not 0 < self.min_coverage <= 1 or not isfinite(self.min_coverage):
            raise ValueError("min_coverage must be in (0,1]")
        if not isinstance(self.min_distinct_dates, int) or self.min_distinct_dates < 3:
            raise ValueError("At least three independent dates are required")
        if (
            not isinstance(self.holdout_dates, int)
            or self.holdout_dates < 1
            or self.holdout_dates >= self.min_distinct_dates
        ):
            raise ValueError("Require at least one holdout and one training date")


@dataclass(frozen=True, slots=True)
class ValidationVerdict:
    status: str
    evidence_days: int
    holdout_case_dates: tuple[str, ...]
    holdout_unit_mae: float | None
    holdout_nodal_price_mae: float | None
    unit_coverage: float
    price_coverage: float
    flow_coverage: float
    reasons: tuple[str, ...]
    historical_only: bool = True
    validated_new_bids: bool = False


def _observations(
    actual: Mapping[str, Any],
    kind: str,
    expected: set[str],
) -> dict[str, Mapping[str, Any]]:
    values = actual.get(kind)
    if not isinstance(values, list) or len(values) != len(expected):
        raise ValueError(f"{kind}: unexpected number of PMSS history rows")
    indexed = {}
    for row in values:
        if not isinstance(row, Mapping):
            raise ValueError(f"{kind}: observed row must be an object")
        if (row.get("market_type") or row.get("marketTypeAtom")) != "DA":
            raise ValueError(f"{kind}: historical row is not DA market")
        ident = row.get("unit_id") or row.get("element_id") or row.get("elementId")
        if ident is None:
            raise ValueError(f"{kind}: missing historical element ID")
        key = str(ident)
        if key in indexed:
            raise ValueError(f"{kind}: duplicate historical element ID")
        indexed[key] = row
    if set(indexed) != expected:
        raise ValueError(f"{kind}: PMSS and modeled IDs disagree")
    return indexed


def _error_metric(errors: Sequence[float], expected: int) -> ErrorMetric:
    return ErrorMetric(
        mae=sum(abs(x) for x in errors) / len(errors) if errors else None,
        rmse=sqrt(sum(x*x for x in errors) / len(errors)) if errors else None,
        observed_points=len(errors),
        expected_points=expected,
    )


def _errors_for_hour(
    actual: Mapping[str, tuple[float | None, ...]],
    simulated: Mapping[str, float],
    hour: int,
    *,
    absolute_values: bool = False,
) -> list[float]:
    errors = []
    for ident, timeseries in actual.items():
        observed = timeseries[hour]
        if observed is None:
            continue
        model = simulated[ident]
        if absolute_values:
            errors.append(abs(model) - abs(observed))
        else:
            errors.append(model - observed)
    return errors


def validate_historical_day(raw: Mapping[str, Any]) -> DayValidation:
    """Reclear EXACT ORIGINAL bids over 24 hours and compare observed DA rows.

    Requires one explicitly dated, sanitized historical snapshot with an
    already verified dcNetwork. This routine is wholly offline and read-only.
    """
    if not isinstance(raw, Mapping):
        raise ValueError("Historical case must be a JSON object")
    if raw.get("historicalBacktestOnly") is not True:
        raise ValueError("Only explicitly labeled historical PMSS cases are accepted")
    day = str(raw.get("caseDate") or "")
    try:
        parsed = date.fromisoformat(day)
    except (TypeError, ValueError) as exc:
        raise ValueError("caseDate must be ISO YYYY-MM-DD for leakage-safe splitting") from exc
    if parsed.isoformat() != day:
        raise ValueError("caseDate must be strictly YYYY-MM-DD")
    if raw.get("results") is None or raw.get("dcNetwork") is None:
        raise ValueError("Historical PMSS results and verified dcNetwork are required")
    observed = raw["results"]
    if not isinstance(observed, Mapping):
        raise ValueError("PMSS observed results must be an object")
    if observed.get("marketTypeAtom") != "DA" or observed.get("periodNum") != 24:
        raise ValueError("Only 24-hour DA market history is supported")

    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"],
        unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    network = network_from_dict(raw["dcNetwork"])
    verify_network_inputs(snapshot, network, snapshot.units[0].unit_id)
    unit_ids = {x.unit_id for x in snapshot.units}
    line_ids = {x.line_id for x in network.lines}
    unit_rows = _observations(observed, "unitResults", unit_ids)
    bus_rows = _observations(observed, "nodalPrices", set(network.buses))
    line_rows = _observations(observed, "branchFlows", line_ids) if line_ids else {}
    powers = {key: series24(row, "accepted_mw", "power") for key, row in unit_rows.items()}
    prices = {key: series24(row, "lmp", "powerFlow") for key, row in bus_rows.items()}
    flows = {
        key: series24(row, "flow_mw", "powerFlow")
        for key, row in line_rows.items()
    }

    # Construct offers from the immutable original snapshot at each hour.
    # This is the only modeled bid set admissible to historical comparison.
    per_unit: dict[str, list[float]] = {u: [] for u in unit_ids}
    all_unit_errors: list[float] = []
    all_price_errors: list[float] = []
    all_flow_errors: list[float] = []
    unit_hour_peak: list[float] = []
    price_hour_peak: list[float] = []
    for hour in range(24):
        offers: list[DcOffer] = []
        for unit in snapshot.units:
            blocks = curve_for_period(snapshot.bids[unit.unit_id], hour + 1)
            if not 1 <= len(blocks) <= snapshot.limits.max_segments:
                raise ValueError(f"Invalid original PMSS segment count: {unit.unit_id}")
            previous = 0.0
            for position, block in enumerate(blocks, 1):
                if (
                    any(not isfinite(x) for x in
                        (block.start_power, block.end_power, block.price))
                    or abs(block.start_power - previous) > 1e-6
                    or block.end_power <= block.start_power
                    or block.price < 0
                ):
                    raise ValueError("Original PMSS offer segment is not a valid DC bid")
                previous = block.end_power
                offers.append(
                    DcOffer(
                        unit_id=unit.unit_id,
                        block=position,
                        quantity_mw=block.quantity_mw,
                        price=block.price,
                    )
                )
            if previous > unit.capacity_mw + 1e-6:
                raise ValueError("Original PMSS bid exceeds declared unit capacity")
        result = dc_clear_hour(network, offers, hour + 1)
        unit_errors = _errors_for_hour(powers, result.accepted_by_unit, hour)
        price_errors = _errors_for_hour(prices, result.nodal_prices, hour)
        flow_errors = _errors_for_hour(
            flows, result.line_flows_mw, hour, absolute_values=True
        )
        all_unit_errors.extend(unit_errors)
        all_price_errors.extend(price_errors)
        all_flow_errors.extend(flow_errors)
        if unit_errors:
            unit_hour_peak.append(sum(abs(x) for x in unit_errors) / len(unit_errors))
        if price_errors:
            price_hour_peak.append(sum(abs(x) for x in price_errors) / len(price_errors))
        for uid in unit_ids:
            observed_power = powers[uid][hour]
            if observed_power is not None:
                per_unit[uid].append(
                    result.accepted_by_unit[uid] - observed_power
                )

    grid_parameters = {
        "buses": sorted(network.buses),
        "lines": sorted((x.line_id, x.from_bus, x.to_bus,
                         x.reactance_pu, x.limit_mw) for x in network.lines),
        "unit_bus": sorted(network.unit_bus.items()),
    }
    fingerprint = sha256(
        json.dumps(grid_parameters, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return DayValidation(
        case_date=day,
        grid_fingerprint=fingerprint,
        unit_count=len(unit_ids),
        bus_count=len(network.buses),
        branch_count=len(network.lines),
        total_demand_mwh=sum(snapshot.demand_forecast_mw),
        unit_dispatch=_error_metric(all_unit_errors, 24 * len(unit_ids)),
        nodal_price=_error_metric(all_price_errors, 24 * len(network.buses)),
        line_flow_abs=_error_metric(all_flow_errors, 24 * len(network.lines)),
        per_unit=tuple(
            UnitError(unit_id=uid, dispatch=_error_metric(per_unit[uid], 24))
            for uid in sorted(unit_ids)
        ),
        max_hourly_dispatch_mae=max(unit_hour_peak, default=None),
        max_hourly_lmp_mae=max(price_hour_peak, default=None),
    )


def _weighted_mae(days: Sequence[DayValidation], attr: str) -> tuple[float | None, float]:
    metrics = [getattr(day, attr) for day in days]
    expected = sum(row.expected_points for row in metrics)
    count = sum(row.observed_points for row in metrics)
    value = (
        sum(row.mae * row.observed_points for row in metrics if row.mae is not None)
        / count
    ) if count else None
    return value, (count / expected if expected else 0.0)


def judge_historical_model(
    cases: Sequence[DayValidation], policy: ValidationPolicy
) -> ValidationVerdict:
    """Chronological holdout gate. Never certify counterfactual PMSS outcomes."""
    dates = [row.case_date for row in cases]
    if len(set(dates)) != len(dates):
        raise ValueError("Duplicate case dates are not independent evidence")
    for label in dates:
        if date.fromisoformat(label).isoformat() != label:
            raise ValueError("Cases require strict ISO calendar dates")
    ordered = sorted(cases, key=lambda row: row.case_date)
    enough = len(ordered) >= policy.min_distinct_dates
    held = ordered[-policy.holdout_dates:] if enough else ordered
    unit_mae, unit_coverage = _weighted_mae(held, "unit_dispatch")
    price_mae, price_coverage = _weighted_mae(held, "nodal_price")
    _, flow_coverage = _weighted_mae(held, "line_flow_abs")
    reasons: list[str] = []
    if not enough:
        reasons.append(
            f"Insufficient independent days: {len(ordered)}/{policy.min_distinct_dates}; "
            "do not certify from a single historical case"
        )
    if any(v < policy.min_coverage for v in (
        unit_coverage, price_coverage, flow_coverage
    )):
        reasons.append("Historical record coverage below user-defined minimum")
    if unit_mae is None or unit_mae > policy.max_unit_dispatch_mae_mw:
        reasons.append("Unit dispatch MAE exceeds user-defined tolerance or is missing")
    if price_mae is None or price_mae > policy.max_nodal_price_mae:
        reasons.append("Nodal price MAE exceeds user-defined tolerance or is missing")
    if any(day.grid_fingerprint != ordered[0].grid_fingerprint for day in ordered):
        reasons.append(
            "Historical topology or line parameters differ; validate each grid separately"
        )
    # A pass is only a historical baseline fit against entered tolerances.
    # It NEVER validates a new bid's outcome under PMSS.
    return ValidationVerdict(
        status="HISTORICAL_BASELINE_WITHIN_TOLERANCE" if not reasons else "NOT_VALIDATED",
        evidence_days=len(ordered),
        holdout_case_dates=tuple(row.case_date for row in held),
        holdout_unit_mae=unit_mae,
        holdout_nodal_price_mae=price_mae,
        unit_coverage=unit_coverage,
        price_coverage=price_coverage,
        flow_coverage=flow_coverage,
        reasons=tuple(reasons),
    )
