"""24h network-constrained unit commitment: integrated MILP + fixed-status DC pricing.

OFFLINE EXPERIMENT ONLY. This is a simplified mixed-integer market dispatch,
not teacher PMSS SCUC/SCED, a validated AC solver, or a market submission.

All generator operating parameters and network data MUST be supplied and
verified. We model hourly offer block dispatch, unit on/start/stop, ramping,
minimum on/off times, nodal balance and DC line limits in the SAME MILP.
After solving, binary status is fixed and a second LP yields *illustrative*
DC nodal dual prices. Raw MILP duals are NOT valid market LMPs.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Literal

from powerbid.network_dispatch import DcNetwork
from powerbid.network_integrity import audit_dc_solution
from powerbid.joint_solution_integrity import audit_joint_schedule
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_integration import PeriodBid, PMSSSnapshot, curve_for_period
from powerbid.unit_commitment import TerminalMode, ThermalConstraints


@dataclass(frozen=True, slots=True)
class JointHour:
    period: int
    demand_mw: float
    accepted_by_unit: dict[str, float]
    unit_online: dict[str, bool]
    unit_started: dict[str, bool]
    unit_stopped: dict[str, bool]
    nodal_prices: dict[str, float]
    line_flows_mw: dict[str, float]
    bid_energy_cost: float
    transition_cost: float


@dataclass(frozen=True, slots=True)
class JointMarketResult:
    hours: tuple[JointHour, ...]
    total_bid_energy_cost: float
    total_transition_cost: float
    total_objective_cost: float
    terminal_mode: TerminalMode
    pricing_method: str = "fixed-commitment continuous LP duals"
    model_label: str = "24h simplified DC+UC MILP, NOT PMSS market clearing"


@dataclass(frozen=True, slots=True)
class JointMwhExtreme:
    """One extreme of the 24h feasible near-minimum *bid+startup* cost set."""

    target_unit_id: str
    direction: Literal["minimum", "maximum"]
    target_accepted_mwh: float
    target_dispatch_24h: tuple[float, ...]
    target_online_24h: tuple[bool, ...]
    primary_optimum_cost: float
    extreme_total_cost: float
    allowed_cost_increase: float
    model_label: str = (
        "24h near-optimal DC+UC feasible dispatch projection; "
        "no LMPs, no verified PMSS counterfactual, no actual settlement"
    )


class JointInfeasibleError(ValueError):
    """No feasible commitment and nodal network dispatch for the entire day."""


def _unit_curves(
    snapshot: PMSSSnapshot,
    target_unit_id: str,
    candidate_plan: Sequence[PeriodBid] | None,
) -> dict[str, tuple[PeriodBid, ...]]:
    if target_unit_id not in snapshot.bids:
        raise ValueError("Unknown target unit")
    plans = dict(snapshot.bids)
    if candidate_plan is not None:
        plans[target_unit_id] = tuple(candidate_plan)
    if snapshot.limits.same_curve:
        for unit_id, periods in plans.items():
            if any(
                curve_for_period(periods, h) != curve_for_period(periods, 1)
                for h in range(2, 25)
            ):
                raise ValueError(f"PMSS same-curve rule violated for {unit_id}")
    return plans


def joint_clear_day(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    technical: Mapping[str, ThermalConstraints],
    target_unit_id: str,
    candidate_plan: Sequence[PeriodBid] | None = None,
    *,
    demand_multiplier: float = 1.0,
    peer_bid_multiplier: float = 1.0,
    terminal_mode: TerminalMode = "complete",
    time_limit_seconds: float = 25.0,
    target_mwh_extreme: Literal["minimum", "maximum"] | None = None,
    extreme_cost_tolerance_abs: float = 1e-5,
    extreme_cost_tolerance_rel: float = 1e-9,
) -> JointMarketResult | JointMwhExtreme:
    """Optimize 24h bid-cost, start/stop and network flow jointly.

    We do not infer actual PMSS startup/dispatch cost or nodal parameters.
    An input called 'start_cost' is a cost *assumption* in the same unit as
    hourly offers. Model demand is in MW with 1-hour market periods.
    """
    verify_network_inputs(snapshot, network, target_unit_id)
    if set(technical) != {x.unit_id for x in snapshot.units}:
        raise ValueError("Every PMSS generator requires an explicit technical record")
    for ident, spec in technical.items():
        if spec.unit_id != ident:
            raise ValueError("ThermalConstraints.unit_id does not match mapping key")
        if not isinstance(spec.initial_on, bool):
            raise ValueError("Initial unit on/off status must be an actual boolean")
        if spec.max_mw > snapshot.unit(ident).capacity_mw + 1e-7:
            raise ValueError(f"{ident}: technical maximum exceeds snapshot capacity")
        if spec.min_mw + 1e-7 < snapshot.unit(ident).min_power_mw:
            raise ValueError(f"{ident}: technical minimum below PMSS snapshot minimum")
    if target_mwh_extreme not in (None, "minimum", "maximum"):
        raise ValueError("target_mwh_extreme must be minimum, maximum or None")
    if any(
        type(value) not in (float, int) or not isfinite(value) or value < 0
        for value in (extreme_cost_tolerance_abs, extreme_cost_tolerance_rel)
    ):
        raise ValueError("MWh extreme cost tolerances must be finite nonnegative")
    if extreme_cost_tolerance_abs > 1 or extreme_cost_tolerance_rel > 1e-5:
        raise ValueError("MWh extreme cost tolerance exceeds safe study limit")
    if terminal_mode not in ("complete", "carryover"):
        raise ValueError("terminal_mode must be complete or carryover")
    for val in (demand_multiplier, peer_bid_multiplier, time_limit_seconds):
        if isinstance(val, bool) or not isfinite(val) or val <= 0:
            raise ValueError("Scenario multipliers and time limit must be finite positive")
    if demand_multiplier > 2 or peer_bid_multiplier > 3:
        raise ValueError("Scenario multiplier is above safe study limit")

    curves = _unit_curves(snapshot, target_unit_id, candidate_plan)
    units = tuple(unit.unit_id for unit in snapshot.units)

    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, linprog, milp
        from scipy.sparse import lil_matrix
    except ImportError as exc:
        raise RuntimeError(
            "Joint DC unit-commitment requires pip install -e '.[strategy]'"
        ) from exc

    c: list[float] = []
    lower: list[float] = []
    upper: list[float] = []
    integer: list[int] = []

    def variable(price: float, lo: float, hi: float, binary: bool = False) -> int:
        ident = len(c)
        c.append(price)
        lower.append(lo)
        upper.append(hi)
        integer.append(1 if binary else 0)
        return ident

    blocks: dict[tuple[int, str], list[int]] = {}
    commitment: dict[tuple[int, str], tuple[int, int, int]] = {}
    flow_vars: dict[tuple[int, str], int] = {}
    hourly_demand: dict[tuple[int, str], float] = {}
    # Reference slack theta=0; every other theta is a free continuous variable.
    theta_vars: dict[tuple[int, str], int] = {}
    angle_buses = [bus for bus in network.buses if bus != network.slack_bus]

    for t in range(24):
        hour = t + 1
        for gen in units:
            block_ids: list[int] = []
            segments = curve_for_period(curves[gen], hour)
            if not 1 <= len(segments) <= snapshot.limits.max_segments:
                raise ValueError(f"{gen}: invalid number of supply bands")
            last = 0.0
            for seg in segments:
                if any(not isfinite(x) for x in (
                    seg.start_power, seg.end_power, seg.price
                )):
                    raise ValueError("A supply band contains nonfinite data")
                if abs(seg.start_power - last) > 1e-6 or seg.end_power <= seg.start_power:
                    raise ValueError("Offer MW segments must be contiguous from zero")
                if seg.price < 0:
                    raise ValueError("Negative supply prices are unsupported in this model")
                last = seg.end_power
                offered_price = seg.price * (
                    1.0 if gen == target_unit_id else peer_bid_multiplier
                )
                block_ids.append(variable(offered_price, 0.0, seg.quantity_mw))
            if last > technical[gen].max_mw + 1e-7:
                raise ValueError(f"{gen}: offer exceeds verified technical maximum")
            blocks[t, gen] = block_ids
            spec = technical[gen]
            commitment[t, gen] = (
                variable(0.0, 0.0, 1.0, True),
                variable(spec.startup_cost, 0.0, 1.0, True),
                variable(spec.shutdown_cost, 0.0, 1.0, True),
            )
        for bus in angle_buses:
            theta_vars[t, bus] = variable(0.0, -np.inf, np.inf)
        for line in network.lines:
            flow_vars[t, line.line_id] = variable(
                0.0, -line.limit_mw, line.limit_mw
            )
        for bus in network.buses:
            hourly_demand[t, bus] = (
                network.hourly_demand_mw[bus][t] * demand_multiplier
            )

    equality: list[dict[int, float]] = []
    equality_rhs: list[float] = []
    inequalities: list[dict[int, float]] = []
    upper_rhs: list[float] = []
    balance_row: dict[tuple[int, str], int] = {}

    def add_eq(values: dict[int, float], rhs: float) -> None:
        equality.append(values)
        equality_rhs.append(rhs)

    def add_le(values: dict[int, float], rhs: float) -> None:
        inequalities.append(values)
        upper_rhs.append(rhs)

    def terms(keys: Sequence[int], factor: float) -> dict[int, float]:
        return {key: factor for key in keys}

    for t in range(24):
        for gen in units:
            spec = technical[gen]
            unit_blocks = blocks[t, gen]
            on, started, stopped = commitment[t, gen]
            all_power = terms(unit_blocks, 1.0)
            add_le({**all_power, on: -spec.max_mw}, 0.0)
            add_le({**terms(unit_blocks, -1.0), on: spec.min_mw}, 0.0)
            if t == 0:
                add_eq(
                    {on: 1.0, started: -1.0, stopped: 1.0},
                    float(spec.initial_on),
                )
                add_le(
                    {**all_power, started: -spec.startup_ramp_mw},
                    spec.initial_mw + spec.ramp_up_mw * float(spec.initial_on),
                )
                add_le(
                    {
                        **terms(unit_blocks, -1.0),
                        on: -spec.ramp_down_mw,
                        stopped: -spec.shutdown_ramp_mw,
                    },
                    -spec.initial_mw,
                )
            else:
                old_on = commitment[t - 1, gen][0]
                preceding = blocks[t - 1, gen]
                add_eq(
                    {on: 1.0, old_on: -1.0, started: -1.0, stopped: 1.0},
                    0.0,
                )
                add_le(
                    {
                        **all_power,
                        **terms(preceding, -1.0),
                        old_on: -spec.ramp_up_mw,
                        started: -spec.startup_ramp_mw,
                    },
                    0.0,
                )
                add_le(
                    {
                        **terms(preceding, 1.0),
                        **terms(unit_blocks, -1.0),
                        on: -spec.ramp_down_mw,
                        stopped: -spec.shutdown_ramp_mw,
                    },
                    0.0,
                )
            add_le({started: 1.0, stopped: 1.0}, 1.0)
            up_begin = max(0, t - spec.min_up_hours + 1)
            add_le(
                {**{commitment[j, gen][1]: 1.0 for j in range(up_begin, t + 1)},
                 on: -1.0},
                0.0,
            )
            down_begin = max(0, t - spec.min_down_hours + 1)
            add_le(
                {**{commitment[j, gen][2]: 1.0 for j in range(down_begin, t + 1)},
                 on: 1.0},
                1.0,
            )
            if spec.initial_on and t < max(
                0, spec.min_up_hours - spec.initial_state_hours
            ):
                add_eq({on: 1.0}, 1.0)
            if not spec.initial_on and t < max(
                0, spec.min_down_hours - spec.initial_state_hours
            ):
                add_eq({on: 1.0}, 0.0)
            if terminal_mode == "complete":
                if t + spec.min_up_hours > 24:
                    add_eq({started: 1.0}, 0.0)
                if t + spec.min_down_hours > 24:
                    add_eq({stopped: 1.0}, 0.0)

        for bus in network.buses:
            row: dict[int, float] = {}
            for gen in units:
                if network.unit_bus[gen] == bus:
                    for index in blocks[t, gen]:
                        row[index] = 1.0
            for line in network.lines:
                flow = flow_vars[t, line.line_id]
                if line.from_bus == bus:
                    row[flow] = -1.0
                elif line.to_bus == bus:
                    row[flow] = 1.0
            balance_row[t, bus] = len(equality)
            add_eq(row, hourly_demand[t, bus])

        for line in network.lines:
            coeff = network.base_mva / line.reactance_pu
            row = {flow_vars[t, line.line_id]: 1.0}
            if line.from_bus != network.slack_bus:
                row[theta_vars[t, line.from_bus]] = -coeff
            if line.to_bus != network.slack_bus:
                row[theta_vars[t, line.to_bus]] = coeff
            add_eq(row, 0.0)

    def matrix(rows: list[dict[int, float]]):
        sparse = lil_matrix((len(rows), len(c)), dtype=float)
        for i, row in enumerate(rows):
            for col, value in row.items():
                sparse[i, col] = value
        return sparse.tocsr()

    a_eq = matrix(equality)
    a_ub = matrix(inequalities)
    c_arr = np.asarray(c, dtype=float)
    lo_arr = np.asarray(lower, dtype=float)
    hi_arr = np.asarray(upper, dtype=float)
    eq_rhs = np.asarray(equality_rhs, dtype=float)
    ub_rhs = np.asarray(upper_rhs, dtype=float)
    mixed = milp(
        c=c_arr,
        integrality=np.asarray(integer, dtype=int),
        bounds=Bounds(lo_arr, hi_arr),
        constraints=[
            LinearConstraint(a_eq, eq_rhs, eq_rhs),
            LinearConstraint(a_ub, -np.inf, ub_rhs),
        ],
        options={"time_limit": time_limit_seconds, "mip_rel_gap": 1e-8},
    )
    if mixed.status == 2:
        raise JointInfeasibleError(
            "No 24-hour dispatch satisfies the combined network and unit constraints"
        )
    if mixed.status != 0 or mixed.x is None:
        raise RuntimeError(
            f"24-hour mixed-integer market dispatch did not prove optimality: "
            f"{mixed.message}"
        )

    if target_mwh_extreme is not None:
        # A second MILP projects the *integrated* 24-hour economic optimum
        # set on the target generator's total accepted MWh. All original
        # network, commitment, start/stop, ramp and bid constraints remain.
        # The two extremes may have different binary unit commitments.
        allowed_cost_increase = (
            extreme_cost_tolerance_abs
            + extreme_cost_tolerance_rel * max(1.0, abs(float(mixed.fun)))
        )
        cost_ceiling = float(mixed.fun) + allowed_cost_increase
        projected_objective = np.zeros_like(c_arr)
        sign = 1.0 if target_mwh_extreme == "minimum" else -1.0
        for t in range(24):
            for idx in blocks[t, target_unit_id]:
                projected_objective[idx] = sign
        projected = milp(
            c=projected_objective,
            integrality=np.asarray(integer, dtype=int),
            bounds=Bounds(lo_arr, hi_arr),
            constraints=[
                LinearConstraint(a_eq, eq_rhs, eq_rhs),
                LinearConstraint(a_ub, -np.inf, ub_rhs),
                LinearConstraint(
                    c_arr.reshape(1, -1), -np.inf, cost_ceiling
                ),
            ],
            options={"time_limit": time_limit_seconds, "mip_rel_gap": 1e-9},
        )
        if projected.status == 2:
            raise JointInfeasibleError(
                "No integrated 24h schedule satisfies the economic optimum face"
            )
        if projected.status != 0 or projected.x is None:
            raise RuntimeError(
                "24h physical MW extreme not proven optimal: "
                + str(projected.message)
            )
        projected_cost = float(c_arr @ projected.x)
        if projected_cost > cost_ceiling + max(1e-4, allowed_cost_increase*1e-3):
            raise RuntimeError("Joint MW extreme violates the primary cost ceiling")
        schedule = tuple(
            sum(max(0.0, float(projected.x[idx]))
                for idx in blocks[t, target_unit_id])
            for t in range(24)
        )
        online = tuple(
            bool(round(projected.x[commitment[t, target_unit_id][0]]))
            for t in range(24)
        )
        # Independently verify the complete projected network solution,
        # not only the objective-cost cap and target MWh.
        for t in range(24):
            dispatch = {
                gen: sum(max(0.0, float(projected.x[idx])) for idx in blocks[t, gen])
                for gen in units
            }
            flows = {
                line.line_id: float(projected.x[flow_vars[t, line.line_id]])
                for line in network.lines
            }
            audit_dc_solution(
                network, dispatch, flows, t + 1,
                load_multiplier=demand_multiplier,
            )
        return JointMwhExtreme(
            target_unit_id=target_unit_id,
            direction=target_mwh_extreme,
            target_accepted_mwh=sum(schedule),
            target_dispatch_24h=schedule,
            target_online_24h=online,
            primary_optimum_cost=float(mixed.fun),
            extreme_total_cost=projected_cost,
            allowed_cost_increase=allowed_cost_increase,
        )

    # Fix ONLY the binary commitment decisions and price the continuous
    # network dispatch. Do not use MILP shadow prices as market LMPs.
    for i, is_binary in enumerate(integer):
        if is_binary:
            fixed = float(round(mixed.x[i]))
            lo_arr[i] = fixed
            hi_arr[i] = fixed
    continuous = linprog(
        c_arr,
        A_eq=a_eq,
        b_eq=eq_rhs,
        A_ub=a_ub,
        b_ub=ub_rhs,
        bounds=list(zip(lo_arr, hi_arr, strict=True)),
        method="highs",
        options={"time_limit": time_limit_seconds},
    )
    if not continuous.success or continuous.x is None:
        raise RuntimeError(
            "Fixed-commitment LP cannot produce reliable illustrative LMPs: "
            + str(continuous.message)
        )
    if abs(continuous.fun - mixed.fun) > max(
        0.1, abs(float(mixed.fun)) * 1e-5
    ):
        raise RuntimeError("Fixed-commitment LP and MILP objectives disagree")

    hours: list[JointHour] = []
    for t in range(24):
        accepted = {
            gen: sum(max(0.0, float(continuous.x[k])) for k in blocks[t, gen])
            for gen in units
        }
        online = {gen: lo_arr[commitment[t, gen][0]] > 0.5 for gen in units}
        started = {gen: lo_arr[commitment[t, gen][1]] > 0.5 for gen in units}
        stopped = {gen: lo_arr[commitment[t, gen][2]] > 0.5 for gen in units}
        bid_cost = sum(
            c_arr[k] * continuous.x[k]
            for gen in units for k in blocks[t, gen]
        )
        transitions = sum(
            spec.startup_cost * started[gen] + spec.shutdown_cost * stopped[gen]
            for gen, spec in technical.items()
        )
        hours.append(
            JointHour(
                period=t+1,
                demand_mw=sum(hourly_demand[t, bus] for bus in network.buses),
                accepted_by_unit=accepted,
                unit_online=online,
                unit_started=started,
                unit_stopped=stopped,
                nodal_prices={
                    bus: float(continuous.eqlin.marginals[balance_row[t, bus]])
                    for bus in network.buses
                },
                line_flows_mw={
                    line.line_id: float(continuous.x[flow_vars[t, line.line_id]])
                    for line in network.lines
                },
                bid_energy_cost=float(bid_cost),
                transition_cost=float(transitions),
            )
        )
    # Independent model audit: nodal KCL, all line MW ratings, DC angle
    # consistency, interhour ramps and explicit binary transitions.
    for hour in hours:
        audit_dc_solution(
            network, hour.accepted_by_unit, hour.line_flows_mw, hour.period,
            load_multiplier=demand_multiplier,
        )
    audit_joint_schedule(technical, hours, terminal_mode=terminal_mode)
    total_bid = sum(row.bid_energy_cost for row in hours)
    total_transition = sum(row.transition_cost for row in hours)
    if abs(total_bid + total_transition - continuous.fun) > max(
        0.1, abs(float(continuous.fun)) * 1e-6
    ):
        raise RuntimeError("Hourly accounting differs from integrated MILP objective")
    return JointMarketResult(
        hours=tuple(hours),
        total_bid_energy_cost=total_bid,
        total_transition_cost=total_transition,
        total_objective_cost=total_bid+total_transition,
        terminal_mode=terminal_mode,
    )
