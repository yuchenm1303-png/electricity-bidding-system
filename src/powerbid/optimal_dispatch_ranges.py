"""Certified optimal-face generator dispatch intervals for a lossless DC LP.

Why? If several equal-price bids are interchangeable, the ordinary HiGHS
solution selects one arbitrary optimal dispatch. A different arbitrary basis
can appear much closer to historical PMSS dispatch *without changing market
offer cost*. The model must report an interval, not claim unique MW values.

Min/max for each unit are separate LPs over the SAME optimal offer-cost
face; all unit extrema need not be simultaneously attainable. The historical
PMSS outputs are NEVER used as price inputs or dispatch constraints.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

from powerbid.network_dispatch import DcNetwork, DcOffer, dc_clear_hour


@dataclass(frozen=True, slots=True)
class OptimalUnitRange:
    unit_id: str
    minimum_mw: float
    maximum_mw: float
    width_mw: float
    baseline_mw: float


@dataclass(frozen=True, slots=True)
class OptimalDispatchRanges:
    period: int
    minimum_offer_cost: float
    allowed_offer_cost_delta: float
    unit_ranges: tuple[OptimalUnitRange, ...]
    unique_dispatch_within_tolerance: bool
    observed_jointly_network_feasible: bool | None = None
    observed_minimum_offer_cost: float | None = None
    observed_bid_cost_gap: float | None = None
    observed_on_optimal_cost_face: bool | None = None
    label: str = (
        "Each range is an independent DC-LP optimum-face projection; "
        "NOT a unique PMSS settlement, nor a joint feasible box"
    )


def optimal_unit_dispatch_ranges(
    network: DcNetwork,
    offers: Sequence[DcOffer],
    period: int,
    *,
    cost_tolerance_abs: float = 1e-6,
    cost_tolerance_rel: float = 1e-10,
    interval_uniqueness_mw: float = 1e-3,
    forced_off_units: frozenset[str] | None = None,
    observed_unit_mw: Mapping[str, float] | None = None,
) -> OptimalDispatchRanges:
    """Find *separate* minimum and maximum output at nearly identical bid cost.

    Original network restrictions are preserved: nodal balance, DC line
    equations, offer-band MW bounds, and line MW limits. Objective-cost
    constraint is the optimum plus a transparent numerical tolerance.
    """
    for tol in (cost_tolerance_abs, cost_tolerance_rel, interval_uniqueness_mw):
        if isinstance(tol, bool) or not isfinite(tol) or tol < 0:
            raise ValueError("Optimal-face tolerances must be finite nonnegative")
    if not 1 <= len(offers) <= 800:
        raise ValueError("Require 1..800 valid original offer bands")
    baseline = dc_clear_hour(
        network, offers, period, forced_off_units=forced_off_units
    )
    forced_off = frozenset() if forced_off_units is None else frozenset(forced_off_units)

    try:
        import numpy as np
        from scipy.optimize import linprog
        from scipy.sparse import lil_matrix, vstack
    except ImportError as exc:
        raise RuntimeError("Optimal-face LP requires optional SciPy strategy dependency") from exc

    nband = len(offers)
    nb = len(network.buses)
    nl = len(network.lines)
    angles = [b for b in network.buses if b != network.slack_bus]
    theta = {bus: nband + i for i, bus in enumerate(angles)}
    flow_start = nband + len(angles)
    size = flow_start + nl
    buses = {bus: i for i, bus in enumerate(network.buses)}
    aeq = lil_matrix((nb + nl, size), dtype=float)
    rhs = np.zeros(nb + nl, dtype=float)
    for bus, i in buses.items():
        rhs[i] = network.hourly_demand_mw[bus][period-1]
    unit_columns: dict[str, list[int]] = {key: [] for key in network.unit_bus}
    prices = np.zeros(size, dtype=float)
    limits: list[tuple[float | None, float | None]] = []
    for i, offer in enumerate(offers):
        if offer.unit_id not in network.unit_bus:
            raise ValueError("Unmapped unit in original offers")
        unit_columns[offer.unit_id].append(i)
        prices[i] = offer.price
        aeq[buses[network.unit_bus[offer.unit_id]], i] = 1.0
        limits.append(
            (0.0, 0.0 if offer.unit_id in forced_off else offer.quantity_mw)
        )
    limits.extend([(None, None)] * len(angles))
    for k, line in enumerate(network.lines):
        col = flow_start+k
        limits.append((-line.limit_mw, line.limit_mw))
        aeq[buses[line.from_bus], col] -= 1.0
        aeq[buses[line.to_bus], col] += 1.0
        aeq[nb+k, col] = 1.0
        coefficient = network.base_mva/line.reactance_pu
        if line.from_bus != network.slack_bus:
            aeq[nb+k, theta[line.from_bus]] -= coefficient
        if line.to_bus != network.slack_bus:
            aeq[nb+k, theta[line.to_bus]] += coefficient

    tolerance = cost_tolerance_abs + cost_tolerance_rel * max(
        1.0, abs(baseline.clearing_offer_cost)
    )
    allowed_cost = baseline.clearing_offer_cost + tolerance
    if allowed_cost < 0:
        raise ValueError("Nonnegative supply price model returned negative total cost")

    aeq = aeq.tocsr()
    # All base bids and constraints remain fixed. Only target unit output
    # becomes the objective for each independent lower/upper projection.
    upper_cost = prices.reshape(1, -1)
    ranges: list[OptimalUnitRange] = []
    for uid in sorted(unit_columns):
        axis = np.zeros(size)
        for column in unit_columns[uid]:
            axis[column] = 1.0
        outcomes: list[float] = []
        for sign in (1, -1):
            fit = linprog(
                sign * axis,
                A_eq=aeq,
                b_eq=rhs,
                A_ub=upper_cost,
                b_ub=[allowed_cost],
                bounds=limits,
                method="highs",
            )
            if not fit.success or fit.x is None:
                raise RuntimeError(
                    f"Could not prove optimal-face output interval for {uid}: "
                    f"{fit.message}"
                )
            if float(prices @ fit.x) > allowed_cost + max(1e-5, tolerance * 1e-3):
                raise RuntimeError("Projected dispatch violates original bid-cost ceiling")
            outcomes.append(float(axis @ fit.x))
        low, high = outcomes
        mid = baseline.accepted_by_unit[uid]
        if low > mid + 1e-3 or high < mid - 1e-3:
            raise RuntimeError("Baseline dispatch fell outside its optimal-face range")
        ranges.append(
            OptimalUnitRange(
                unit_id=uid,
                minimum_mw=max(0.0, low),
                maximum_mw=max(0.0, high),
                width_mw=max(0.0, high-low),
                baseline_mw=mid,
            )
        )
    observed_feasible: bool | None = None
    observed_cost: float | None = None
    observed_gap: float | None = None
    observed_optimal: bool | None = None
    if observed_unit_mw is not None:
        if set(observed_unit_mw) != set(unit_columns):
            raise ValueError("Observed dispatch must include every mapped generator")
        if any(
            isinstance(value, bool) or not isfinite(value) or value < 0
            for value in observed_unit_mw.values()
        ):
            raise ValueError("Observed generator MW values must be finite nonnegative")
        observed_rows = lil_matrix((len(unit_columns), size), dtype=float)
        observed_targets = np.zeros(len(unit_columns))
        for idx, uid in enumerate(sorted(unit_columns)):
            observed_targets[idx] = observed_unit_mw[uid]
            for col in unit_columns[uid]:
                observed_rows[idx, col] = 1.0
        observed_result = linprog(
            prices,
            A_eq=vstack([aeq, observed_rows.tocsr()], format="csr"),
            b_eq=np.concatenate([rhs, observed_targets]),
            bounds=limits,
            method="highs",
        )
        observed_feasible = observed_result.status == 0
        if observed_feasible and observed_result.fun is not None:
            observed_cost = float(observed_result.fun)
            observed_gap = max(0.0, observed_cost-baseline.clearing_offer_cost)
            observed_optimal = observed_gap <= tolerance + 1e-5
        elif observed_result.status != 2:
            raise RuntimeError(
                "Could not verify observed dispatch against network: "
                + str(observed_result.message)
            )

    return OptimalDispatchRanges(
        period=period,
        minimum_offer_cost=baseline.clearing_offer_cost,
        allowed_offer_cost_delta=tolerance,
        unit_ranges=tuple(ranges),
        unique_dispatch_within_tolerance=all(
            unit.width_mw <= interval_uniqueness_mw for unit in ranges
        ),
        observed_jointly_network_feasible=observed_feasible,
        observed_minimum_offer_cost=observed_cost,
        observed_bid_cost_gap=observed_gap,
        observed_on_optimal_cost_face=observed_optimal,
    )
