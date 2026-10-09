"""Offline comparison of user-associated historical market results.

This never accesses PMSS or submits a bid. An operator's association
statement does not authenticate the teacher's result or prove causality.
"""
from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Any

from powerbid.pmss_diagnostics import series24
from powerbid.pmss_integration import BidSegment, PMSSSnapshot
from powerbid.pmss_bid_rule_safety import validate_new_curve
from powerbid.pmss_strategy import evaluate_curve


def review_manual_result(
    snapshot: PMSSSnapshot,
    *,
    target_unit_id: str,
    case_date: str,
    uploaded_date: str,
    recommended_segments: list[BidSegment],
    results: dict[str, Any],
    operator_confirmed: bool,
    original_results: dict[str, Any] | None,
) -> dict[str, Any]:
    if operator_confirmed is not True:
        raise ValueError("Operator must explicitly confirm the result association")
    if type(case_date) is not str or len(case_date) != 10:
        raise ValueError("Invalid study case date")
    try:
        if date.fromisoformat(case_date).isoformat() != case_date:
            raise ValueError("Invalid date")
    except ValueError as exc:
        raise ValueError("Invalid study case date") from exc
    if uploaded_date != case_date:
        raise ValueError("Different study and observed result dates")
    if results.get("marketTypeAtom") != "DA" or type(results.get("periodNum")) is not int or results["periodNum"] != 24:
        raise ValueError("Expected a 24-hour DA result")
    if original_results is not None and results == original_results:
        raise ValueError("Result file repeats the original historical baseline")
    validate_new_curve(snapshot, target_unit_id, recommended_segments)
    units = results.get("unitResults")
    if not isinstance(units, list) or not 1 <= len(units) <= 30 or any(not isinstance(x, dict) for x in units):
        raise ValueError("Invalid unit-result list")
    ids = [str(x.get("unit_id", x.get("elementId", ""))) for x in units]
    if len(set(ids)) != len(ids) or set(ids) - set(snapshot.bids) or ids.count(target_unit_id) != 1:
        raise ValueError("Result generator IDs do not match selected case")
    if any(x.get("market_type", x.get("marketTypeAtom")) != "DA" for x in units):
        raise ValueError("Only day-ahead results may be compared")
    unit = units[ids.index(target_unit_id)]
    accepted = series24(unit, "accepted_mw", "power")
    capacity = snapshot.unit(target_unit_id).capacity_mw
    if any(x is None or x < 0 or x > capacity + 1e-5 for x in accepted):
        raise ValueError("24 complete in-range observed MW values required")
    prices = series24(unit, "clearing_prices", "price") if ("clearing_prices" in unit or "price" in unit) else (None,) * 24
    incomes = series24(unit, "income") if "income" in unit else (None,) * 24
    predicted = evaluate_curve(snapshot, target_unit_id, recommended_segments)
    rows = []
    for period, (actual, simulated, price, income) in enumerate(zip(accepted, predicted.hours, prices, incomes, strict=True), 1):
        if simulated.period != period:
            raise ValueError("Local hours must be 1..24")
        rows.append({
            "period": period, "observed_accepted_mw": actual,
            "local_surrogate_accepted_mw": simulated.target_accepted_mw,
            "observed_unit_price": price, "reported_income": income,
        })
    observed_mwh = sum(accepted)
    return {
        "case_date": case_date, "target_unit_id": target_unit_id,
        "periods": 24, "shared_curve_24h": True,
        "observed_accepted_mwh": observed_mwh,
        "local_surrogate_accepted_mwh": predicted.total_accepted_mwh,
        "hourly_dispatch_mae_mw": mean(abs(x["observed_accepted_mw"]-x["local_surrogate_accepted_mw"]) for x in rows),
        "reported_income_sum": sum(incomes) if all(x is not None for x in incomes) else None,
        "income_coverage": sum(x is not None for x in incomes),
        "price_coverage": sum(x is not None for x in prices),
        "hours": rows,
        "association": "OPERATOR_ASSERTED_ONLY",
        "teacher_result_authenticated": False,
        "candidate_bid_causality_verified": False,
        "reported_income_is_net_profit": False,
        "pmss_write_performed": False,
        "pmss_clearing_executed": False,
        "automatic_submission_enabled": False,
    }
