"""Historical read-only price-output hypothesis testing, never a PMSS rule claim.

The same historical ORIGINAL offers are cleared with the existing lossless
DC-LP engine. We compare its UNALTERED nodal duals with observed PMSS DA
prices, then compare explicit hypothetical output ceilings applied ONLY to
copies of those simulated prices. No bid offer, solver objective, settlement
calculation or candidate-strategy score is changed.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any

from powerbid.network_dispatch import DcOffer, dc_clear_hour, network_from_dict
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_diagnostics import series24
from powerbid.pmss_integration import curve_for_period, snapshot_from_pmss


@dataclass(frozen=True, slots=True)
class PriceHypothesis:
    label: str
    ceiling: float | None
    observed_points: int
    mae: float | None
    rmse: float | None
    matching_points: int
    improved_points_vs_uncapped: int
    worsened_points_vs_uncapped: int


@dataclass(frozen=True, slots=True)
class PriceDiagnosticHour:
    period: int
    observed_points: int
    raw_mae: float | None
    raw_mismatching_points: int
    raw_peak_price: float
    observed_peak_price: float | None
    capped_mae_by_hypothesis: tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class HistoricalPriceHypothesisAudit:
    case_date: str
    node_count: int
    expected_points: int
    observed_points: int
    price_ceiling_in_current_market_rule: float | None
    maximum_price_in_saved_original_offers: float
    historical_offer_segments_above_current_rule: int
    hypotheses: tuple[PriceHypothesis, ...]
    hours: tuple[PriceDiagnosticHour, ...]
    historically_exact_price_fit_for_any_hypothesis: bool
    validated_new_bids: bool = False
    model_label: str = (
        "EX-POST PMSS ORIGINAL-offer nodal price reporting hypothesis; "
        "NOT proof of PMSS price rule, prospective LMP, new-bid profit "
        "or authorization to change candidate price limits"
    )


def _observed_node_prices(
    observed: Mapping[str, Any], nodes: set[str]
) -> dict[str, tuple[float | None, ...]]:
    if observed.get("marketTypeAtom") != "DA" or observed.get("periodNum") != 24:
        raise ValueError("Historical PMSS prices must be matching 24h DA data")
    rows = observed.get("nodalPrices")
    if not isinstance(rows, list) or len(rows) != len(nodes):
        raise ValueError("Historical price rows must cover every verified node")
    readings: dict[str, tuple[float | None, ...]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Historical price record is not an object")
        if (row.get("market_type") or row.get("marketTypeAtom")) != "DA":
            raise ValueError("Historical price row is not DA market")
        key = row.get("element_id") or row.get("elementId") or row.get("unit_id")
        if key is None or str(key) in readings:
            raise ValueError("Missing or duplicate historical node ID")
        readings[str(key)] = series24(row, "lmp", "powerFlow")
    if set(readings) != nodes:
        raise ValueError("Observed prices and verified network IDs differ")
    return readings


def _mae(values: Sequence[float]) -> float | None:
    return sum(abs(v) for v in values) / len(values) if values else None


def audit_historical_price_caps(
    raw: Mapping[str, Any],
    *,
    hypothetical_ceilings: Sequence[float] = (1000.0, 1001.0),
    match_tolerance: float = 1e-5,
) -> HistoricalPriceHypothesisAudit:
    """Evaluate up to four explicitly hypothetical price-reporting ceilings.

    These hypotheses apply ONLY to reported simulated *nodal prices* AFTER
    optimizing original offers. They do NOT clip bids, dispatch, node duals
    inside the solver, or any subsequent pricing/settlement flow.
    """
    if not isinstance(raw, Mapping) or raw.get("historicalBacktestOnly") is not True:
        raise ValueError("Only explicitly tagged historical PMSS cases are accepted")
    label = str(raw.get("caseDate") or "")
    try:
        parsed = date.fromisoformat(label)
    except (ValueError, TypeError) as exc:
        raise ValueError("caseDate must be ISO YYYY-MM-DD") from exc
    if parsed.isoformat() != label:
        raise ValueError("caseDate must be ISO YYYY-MM-DD")
    if not isinstance(match_tolerance, (int, float)) or (
        isinstance(match_tolerance, bool) or not isfinite(match_tolerance)
        or match_tolerance < 0 or match_tolerance > 0.1
    ):
        raise ValueError("Price match tolerance must be between 0 and 0.1")
    if not 1 <= len(hypothetical_ceilings) <= 4:
        raise ValueError("Choose between one and four diagnostic ceiling hypotheses")
    ceilings = tuple(hypothetical_ceilings)
    if any(isinstance(v, bool) or not isfinite(v) or v < 0 or v > 100_000
           for v in ceilings):
        raise ValueError("Hypothetical price ceilings must be finite nonnegative")
    if len(set(ceilings)) != len(ceilings):
        raise ValueError("Duplicate hypothetical ceiling values")

    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"],
        unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    network = network_from_dict(raw["dcNetwork"])
    verify_network_inputs(snapshot, network, snapshot.units[0].unit_id)
    observed = raw.get("results")
    if not isinstance(observed, Mapping):
        raise ValueError("Observed original PMSS results are required")
    measurements = _observed_node_prices(observed, set(network.buses))

    values = (None, *ceilings)
    errors: list[list[float]] = [[] for _ in values]
    matching: list[int] = [0] * len(values)
    improved: list[int] = [0] * len(values)
    worsened: list[int] = [0] * len(values)
    hours = []
    max_saved_bid = float("-inf")
    above_rule_segments = 0
    price_ceiling = snapshot.limits.price_ceiling

    # PMSS saved historic curves are not rewritten to satisfy today's rules.
    for generator in snapshot.units:
        for period in snapshot.bids[generator.unit_id]:
            for segment in period.segments:
                max_saved_bid = max(max_saved_bid, segment.price)
                if price_ceiling is not None and segment.price > price_ceiling:
                    above_rule_segments += 1

    for period in range(1, 25):
        offers = []
        for generator in snapshot.units:
            segments = curve_for_period(snapshot.bids[generator.unit_id], period)
            if not 1 <= len(segments) <= snapshot.limits.max_segments:
                raise ValueError("Invalid original historical offer bands")
            last = 0.0
            for index, segment in enumerate(segments, 1):
                if any(not isfinite(x) for x in (
                    segment.start_power, segment.end_power, segment.price
                )) or (
                    abs(last - segment.start_power) > 1e-6
                    or segment.end_power <= segment.start_power
                    or segment.price < 0
                ):
                    raise ValueError("Invalid original PMSS supply curve")
                last = segment.end_power
                offers.append(DcOffer(
                    generator.unit_id, index, segment.quantity_mw, segment.price
                ))
            if last > generator.capacity_mw + 1e-6:
                raise ValueError("Historical offer exceeds known physical MW capacity")
        solved = dc_clear_hour(network, offers, period)
        hourly_errors: list[list[float]] = [[] for _ in values]
        valid_prices = []
        for bus, historic in measurements.items():
            measured = historic[period-1]
            if measured is None:
                continue
            valid_prices.append(measured)
            model_price = solved.nodal_prices[bus]
            baseline_error = abs(model_price - measured)
            for idx, ceiling in enumerate(values):
                adjusted = model_price if ceiling is None else min(model_price, ceiling)
                error = abs(adjusted-measured)
                hourly_errors[idx].append(error)
                errors[idx].append(error)
                matching[idx] += error <= match_tolerance
                if idx:
                    improved[idx] += error < baseline_error-match_tolerance
                    worsened[idx] += error > baseline_error+match_tolerance
        hours.append(PriceDiagnosticHour(
            period=period,
            observed_points=len(valid_prices),
            raw_mae=_mae(hourly_errors[0]),
            raw_mismatching_points=sum(x > match_tolerance for x in hourly_errors[0]),
            raw_peak_price=max(solved.nodal_prices.values()),
            observed_peak_price=max(valid_prices) if valid_prices else None,
            capped_mae_by_hypothesis=tuple(
                _mae(row) for row in hourly_errors[1:]
            ),
        ))
    hypothesis = tuple(
        PriceHypothesis(
            label="Unmodified DC dual LMP" if ceiling is None
            else f"EX-POST output ceiling {ceiling:g}",
            ceiling=ceiling,
            observed_points=len(errors[idx]),
            mae=_mae(errors[idx]),
            rmse=(
                (sum(value*value for value in errors[idx])/len(errors[idx]))**0.5
                if errors[idx] else None
            ),
            matching_points=matching[idx],
            improved_points_vs_uncapped=improved[idx],
            worsened_points_vs_uncapped=worsened[idx],
        )
        for idx, ceiling in enumerate(values)
    )
    return HistoricalPriceHypothesisAudit(
        case_date=label,
        node_count=len(network.buses),
        expected_points=24 * len(network.buses),
        observed_points=len(errors[0]),
        price_ceiling_in_current_market_rule=price_ceiling,
        maximum_price_in_saved_original_offers=max_saved_bid,
        historical_offer_segments_above_current_rule=above_rule_segments,
        hypotheses=hypothesis,
        hours=tuple(hours),
        historically_exact_price_fit_for_any_hypothesis=bool(errors[0]) and any(
            row.matching_points == len(errors[0]) for row in hypothesis
        ),
    )
