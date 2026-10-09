"""Deterministic SECONDARY DC dispatch selection on a primary bid-cost optimum face.

Original DC-LP minimizes hourly offered electricity cost. If identical-cost
unit allocations are not unique, a stable, explicitly selected generator-ID
lexicographic priority selects ONE of the equivalent-cost feasible allocations.
This is an EX-ANTE research convention, NOT a discovered PMSS dispatch rule.

Primary objective cost is protected by an explicit tolerance constraint.
Never take dual prices of the secondary LP as PMSS nodal prices. Original
baseline DC duals are returned *separately* as unmodified model diagnostics.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from powerbid.network_dispatch import (
    DcNetwork,
    DcOffer,
    dc_clear_hour,
)

# Explicit tiny numerical allowance only: not a PMSS market rule.
DEFAULT_PRIMARY_COST_TOLERANCE_ABS = 1e-6
DEFAULT_PRIMARY_COST_TOLERANCE_REL = 1e-10


@dataclass(frozen=True, slots=True)
class DeterministicDcDispatch:
    period: int
    policy: str
    unit_priority: tuple[str, ...]
    selected_mw: dict[str, float]
    line_flows_mw: dict[str, float]
    original_lp_selected_mw: dict[str, float]
    original_model_nodal_prices: dict[str, float]
    primary_optimum_bid_cost: float
    selected_bid_cost: float
    allowed_primary_cost_increase: float
    disclaimer: str = (
        "Illustrative deterministic optimum-face tie-break, NOT proven PMSS "
        "priority or actual clearing; nodal prices are from original primary "
        "DC LP, NOT from the secondary tie-break objective."
    )


def select_dc_optimal_tiebreak(
    network: DcNetwork,
    offers: Sequence[DcOffer],
    period: int,
    *,
    unit_priority: Sequence[str] | None = None,
    max_cost_increase_abs: float = DEFAULT_PRIMARY_COST_TOLERANCE_ABS,
    max_cost_increase_rel: float = DEFAULT_PRIMARY_COST_TOLERANCE_REL,
    time_limit_seconds: float = 12,
) -> DeterministicDcDispatch:
    """Maximize MW for each ordered unit sequentially, keeping lower ranks fixed.

    Only the generator order chooses among near-primary-optimal feasible
    dispatches. Every phase preserves hourly demand, DC line physics,
    MW bounds and an EXPLICIT tiny primary bid-cost tolerance. A 1e-10
    relative cost tolerance avoids false HiGHS infeasibility when several
    sequential lexicographic equality locks accumulate numerical error
    (observed on historical high-price multi-unit LP cases). It is a
    solver feasibility allowance, NEVER a fitted PMSS dispatch rule.
    All band input ordering is canonicalized, so permuted source JSON
    never silently changes ranking.
    """
    if not 1 <= period <= 24:
        raise ValueError("period must be 1..24")
    if not 1 <= len(offers) <= 800:
        raise ValueError("Require 1..800 valid offer bands")
    for value in (max_cost_increase_abs, max_cost_increase_rel):
        if isinstance(value, bool) or not isfinite(value) or value < 0:
            raise ValueError("Primary cost tolerance must be finite nonnegative")
    if (isinstance(time_limit_seconds, bool) or
            not isfinite(time_limit_seconds) or time_limit_seconds <= 0):
        raise ValueError("Time limit must be finite positive")
    units = tuple(sorted(network.unit_bus))
    priority = units if unit_priority is None else tuple(unit_priority)
    if len(priority) != len(units) or set(priority) != set(units):
        raise ValueError("Unit priority must contain each mapped unit ID exactly once")
    if len(set(priority)) != len(priority):
        raise ValueError("Duplicate generator in unit priority")
    ordered = tuple(sorted(offers, key=lambda offer: (offer.unit_id, offer.block)))
    original = dc_clear_hour(
        network, ordered, period, time_limit_seconds=time_limit_seconds
    )
    try:
        import numpy as np
        from scipy.optimize import linprog
        from scipy.sparse import lil_matrix, vstack
    except ImportError as exc:
        raise RuntimeError("Requires SciPy strategy optional dependency") from exc

    nband, nb, nl = len(ordered), len(network.buses), len(network.lines)
    bus_id = {bus: i for i, bus in enumerate(network.buses)}
    angle_buses = [bus for bus in network.buses if bus != network.slack_bus]
    theta_id = {bus: nband + i for i, bus in enumerate(angle_buses)}
    flow_start = nband + len(angle_buses)
    nvar = flow_start + nl
    equations = lil_matrix((nb + nl, nvar), dtype=float)
    rhs = np.zeros(nb + nl)
    for bus, idx in bus_id.items():
        rhs[idx] = network.hourly_demand_mw[bus][period - 1]
    primary_prices = np.zeros(nvar)
    bounds: list[tuple[float | None, float | None]] = []
    unit_columns = {uid: [] for uid in units}
    for i, item in enumerate(ordered):
        if item.unit_id not in network.unit_bus:
            raise ValueError("Offer unit not found in network")
        primary_prices[i] = item.price
        unit_columns[item.unit_id].append(i)
        bounds.append((0., item.quantity_mw))
        equations[bus_id[network.unit_bus[item.unit_id]], i] = 1.
    if set(uid for uid, columns in unit_columns.items() if columns) != set(units):
        raise ValueError("All mapped generators require supply offers")
    if len({(o.unit_id, o.block) for o in ordered}) != len(ordered):
        raise ValueError("Duplicate unit/block offer band")
    bounds.extend([(None, None)] * len(angle_buses))
    for j, line in enumerate(network.lines):
        flow_col = flow_start+j
        bounds.append((-line.limit_mw, line.limit_mw))
        equations[bus_id[line.from_bus], flow_col] -= 1.
        equations[bus_id[line.to_bus], flow_col] += 1.
        equations[nb+j, flow_col] = 1.
        x_factor = network.base_mva/line.reactance_pu
        if line.from_bus != network.slack_bus:
            equations[nb+j, theta_id[line.from_bus]] -= x_factor
        if line.to_bus != network.slack_bus:
            equations[nb+j, theta_id[line.to_bus]] += x_factor

    base_cost = original.clearing_offer_cost
    # Cost-optimality is measured in the original offer objective units.
    # Tiny relative slack is needed for multiple sequential LP equality
    # locks at large objective scale; NEVER relax voltage/line or MW limits.
    tolerance = max_cost_increase_abs + max_cost_increase_rel*max(1., abs(base_cost))
    cost_upper = base_cost + tolerance
    locked = lil_matrix((0, nvar), dtype=float).tocsr()
    locked_rhs: list[float] = []
    base_eq = equations.tocsr()
    chosen_x = None
    for uid in priority:
        objective = np.zeros(nvar)
        objective[unit_columns[uid]] = -1.
        solve = linprog(
            objective,
            A_eq=vstack([base_eq, locked], format="csr"),
            b_eq=np.r_[rhs, np.asarray(locked_rhs)],
            A_ub=primary_prices.reshape(1, -1),
            b_ub=[cost_upper],
            bounds=bounds,
            method="highs",
            options={"time_limit": time_limit_seconds},
        )
        if not solve.success or solve.x is None:
            raise RuntimeError(
                f"Cannot prove stable secondary tie-break for {uid}: {solve.message}"
            )
        chosen_x = solve.x
        target = sum(float(chosen_x[col]) for col in unit_columns[uid])
        row = lil_matrix((1, nvar), dtype=float)
        for col in unit_columns[uid]:
            row[0, col] = 1.
        locked = vstack([locked, row.tocsr()], format="csr")
        locked_rhs.append(target)

    if chosen_x is None:
        raise RuntimeError("No generator priority could be evaluated")
    selected_cost = float(primary_prices @ chosen_x)
    if selected_cost > cost_upper + max(1e-5, tolerance*1e-3):
        raise RuntimeError("Secondary dispatch exceeds primary bid-cost tolerance")
    result_mw = {
        uid: sum(max(0., float(chosen_x[i])) for i in unit_columns[uid])
        for uid in units
    }
    if abs(sum(result_mw.values()) - original.demand_mw) > 1e-4:
        raise RuntimeError("Secondary dispatch violates hourly generation/load balance")
    return DeterministicDcDispatch(
        period=period,
        policy="explicit unit-ID lexicographic MW priority",
        unit_priority=priority,
        selected_mw=result_mw,
        line_flows_mw={
            line.line_id: float(chosen_x[flow_start+j])
            for j, line in enumerate(network.lines)
        },
        original_lp_selected_mw=original.accepted_by_unit,
        original_model_nodal_prices=original.nodal_prices,
        primary_optimum_bid_cost=base_cost,
        selected_bid_cost=selected_cost,
        allowed_primary_cost_increase=tolerance,
    )
