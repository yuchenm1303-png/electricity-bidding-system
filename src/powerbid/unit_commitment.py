"""24-hour unit commitment against an EXOGENOUS price forecast.

This is a standalone planning and physical-feasibility module, not the PMSS
clearing engine. Technical constraints MUST be supplied explicitly by users
or verified course data; PMSS's unit tree alone is insufficient.

The MILP uses SciPy/HiGHS (optional dependency). It respects Pmin/Pmax,
on/off status, start/stop decisions, minimum on/off durations, hourly ramps,
startup/shutdown transition ramps and startup/shutdown cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal, Sequence

TerminalMode = Literal["complete", "carryover"]
HOURS = 24
EPS = 1e-6


@dataclass(frozen=True, slots=True)
class ThermalConstraints:
    unit_id: str
    min_mw: float
    max_mw: float
    ramp_up_mw: float
    ramp_down_mw: float
    startup_ramp_mw: float
    shutdown_ramp_mw: float
    min_up_hours: int
    min_down_hours: int
    startup_cost: float
    shutdown_cost: float
    initial_on: bool
    initial_mw: float
    initial_state_hours: int

    def __post_init__(self) -> None:
        if not self.unit_id.strip():
            raise ValueError("unit_id must not be empty")
        quantities = (
            self.min_mw, self.max_mw, self.ramp_up_mw,
            self.ramp_down_mw, self.startup_ramp_mw,
            self.shutdown_ramp_mw, self.startup_cost,
            self.shutdown_cost, self.initial_mw,
        )
        if any(isinstance(v, bool) or not isfinite(v) or v < 0 for v in quantities):
            raise ValueError("Physical parameters must be finite and non-negative")
        if self.max_mw <= 0 or self.min_mw > self.max_mw:
            raise ValueError("Require 0 <= min_mw <= max_mw and max_mw > 0")
        if not 0 <= self.initial_mw <= self.max_mw:
            raise ValueError("Initial power outside unit bounds")
        if self.initial_on:
            if self.initial_mw + EPS < self.min_mw:
                raise ValueError("Online initial power must meet technical minimum")
        elif self.initial_mw > EPS:
            raise ValueError("Offline initial unit must have zero output")
        for label, value in (
            ("min_up_hours", self.min_up_hours),
            ("min_down_hours", self.min_down_hours),
            ("initial_state_hours", self.initial_state_hours),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{label} must be a positive integer")


@dataclass(frozen=True, slots=True)
class DispatchHour:
    period: int
    online: bool
    power_mw: float
    started: bool
    stopped: bool
    forecast_price: float
    energy_margin: float
    transition_cost: float
    net_margin: float


@dataclass(frozen=True, slots=True)
class CommitmentPlan:
    unit_id: str
    hourly: tuple[DispatchHour, ...]
    forecast_source: str
    total_energy_mwh: float
    gross_margin: float
    transition_cost: float
    net_margin: float
    terminal_mode: TerminalMode
    remaining_required_hours: int


@dataclass(frozen=True, slots=True)
class FeasibilityAudit:
    feasible: bool
    violations: tuple[str, ...]
    starts: int
    stops: int
    remaining_required_hours: int


def _terminal_mode(mode: str) -> TerminalMode:
    if mode not in ("complete", "carryover"):
        raise ValueError("terminal_mode must be 'complete' or 'carryover'")
    return mode  # type: ignore[return-value]


def _forecast(values: Sequence[float], label: str) -> tuple[float, ...]:
    if len(values) != HOURS:
        raise ValueError(f"{label} must contain exactly 24 hourly values")
    if any(isinstance(v, bool) or not isfinite(float(v)) for v in values):
        raise ValueError(f"{label} values must be finite")
    return tuple(float(v) for v in values)


def audit_dispatch(
    spec: ThermalConstraints,
    dispatch_mw: Sequence[float],
    *,
    terminal_mode: TerminalMode = "complete",
) -> FeasibilityAudit:
    """Inspect exogenous *accepted* dispatch; does not modify or optimize it.

    When Pmin=0, zero output is treated as offline. This is inherently unable
    to infer whether a zero-output, zero-Pmin unit was actually committed.
    """
    mode = _terminal_mode(terminal_mode)
    values = _forecast(dispatch_mw, "dispatch_mw")
    violations: list[str] = []
    previous_on = spec.initial_on
    previous_mw = spec.initial_mw
    elapsed = spec.initial_state_hours
    starts = stops = 0

    for hour, power in enumerate(values, 1):
        if power < -EPS:
            violations.append(f"hour {hour}: negative generation")
        if power > spec.max_mw + EPS:
            violations.append(f"hour {hour}: exceeds maximum generation")
        on = power > EPS
        if on and power + EPS < spec.min_mw:
            violations.append(f"hour {hour}: below technical minimum")
        if on != previous_on:
            needed = spec.min_up_hours if previous_on else spec.min_down_hours
            if elapsed < needed:
                violations.append(
                    f"hour {hour}: premature {'stop' if previous_on else 'start'} "
                    f"(previous state lasted {elapsed}h, requires {needed}h)"
                )
            if on:
                starts += 1
                if power > spec.startup_ramp_mw + EPS:
                    violations.append(f"hour {hour}: startup ramp exceeded")
            else:
                stops += 1
                if previous_mw > spec.shutdown_ramp_mw + EPS:
                    violations.append(f"hour {hour}: shutdown ramp exceeded")
            elapsed = 1
        else:
            elapsed += 1
            if on and power - previous_mw > spec.ramp_up_mw + EPS:
                violations.append(f"hour {hour}: upward ramp exceeded")
            if on and previous_mw - power > spec.ramp_down_mw + EPS:
                violations.append(f"hour {hour}: downward ramp exceeded")
        previous_on, previous_mw = on, power

    required = spec.min_up_hours if previous_on else spec.min_down_hours
    remaining = max(0, required - elapsed)
    if mode == "complete" and remaining:
        violations.append(
            f"terminal state requires {remaining} more hours beyond horizon"
        )
    return FeasibilityAudit(
        feasible=not violations,
        violations=tuple(violations),
        starts=starts,
        stops=stops,
        remaining_required_hours=remaining,
    )


class CommitmentSolveError(RuntimeError):
    """The unit-commitment MILP has no feasible solution or solver failed."""


def optimize_unit_commitment(
    spec: ThermalConstraints,
    forecast_prices: Sequence[float],
    *,
    energy_cost_per_mwh: float,
    forecast_source: str,
    terminal_mode: TerminalMode = "complete",
    time_limit_seconds: float = 15.0,
) -> CommitmentPlan:
    """Maximize forecast energy margin minus start/stop costs over 24 hours.

    The forecast is treated as *exogenous*: this does not model price impact,
    network congestion, market bid acceptance, reserves, or PMSS settlement.
    """
    mode = _terminal_mode(terminal_mode)
    prices = _forecast(forecast_prices, "forecast_prices")
    if not forecast_source.strip():
        raise ValueError("A traceable forecast_source is required")
    if not isfinite(energy_cost_per_mwh) or energy_cost_per_mwh < 0:
        raise ValueError("energy_cost_per_mwh must be finite and non-negative")
    if not isfinite(time_limit_seconds) or time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be finite and positive")
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import lil_matrix
    except ImportError as exc:
        raise RuntimeError(
            "24h unit commitment requires optional dependency: "
            "pip install -e '.[strategy]'"
        ) from exc

    # Each hour has variables [p, on, start, stop].
    def p(t: int) -> int:
        return 4 * t

    def u(t: int) -> int:
        return 4 * t + 1

    def start(t: int) -> int:
        return 4 * t + 2

    def stop(t: int) -> int:
        return 4 * t + 3

    size = HOURS * 4
    objective = np.zeros(size, dtype=float)
    integrality = np.zeros(size, dtype=int)
    lower = np.zeros(size)
    upper = np.ones(size)
    for t in range(HOURS):
        objective[p(t)] = energy_cost_per_mwh - prices[t]
        objective[start(t)] = spec.startup_cost
        objective[stop(t)] = spec.shutdown_cost
        upper[p(t)] = spec.max_mw
        integrality[[u(t), start(t), stop(t)]] = 1

    rows: list[dict[int, float]] = []
    lower_rows: list[float] = []
    upper_rows: list[float] = []

    def add(coefficients: dict[int, float], lb: float = -np.inf, ub: float = np.inf):
        rows.append(coefficients)
        lower_rows.append(lb)
        upper_rows.append(ub)

    for t in range(HOURS):
        # Pmin*on <= p <= Pmax*on
        add({p(t): 1.0, u(t): -spec.max_mw}, ub=0.0)
        add({p(t): -1.0, u(t): spec.min_mw}, ub=0.0)
        # on[t] - on[t-1] = start[t] - stop[t]
        if t == 0:
            add(
                {u(t): 1.0, start(t): -1.0, stop(t): 1.0},
                lb=float(spec.initial_on),
                ub=float(spec.initial_on),
            )
            # Startup and shutdown transitions have their own explicit ramps.
            add(
                {p(t): 1.0, start(t): -spec.startup_ramp_mw},
                ub=spec.initial_mw + spec.ramp_up_mw * float(spec.initial_on),
            )
            add(
                {p(t): -1.0, u(t): -spec.ramp_down_mw,
                 stop(t): -spec.shutdown_ramp_mw},
                ub=-spec.initial_mw,
            )
        else:
            add(
                {u(t): 1.0, u(t-1): -1.0, start(t): -1.0, stop(t): 1.0},
                lb=0.0, ub=0.0,
            )
            add(
                {p(t): 1.0, p(t-1): -1.0,
                 u(t-1): -spec.ramp_up_mw, start(t): -spec.startup_ramp_mw},
                ub=0.0,
            )
            add(
                {p(t-1): 1.0, p(t): -1.0,
                 u(t): -spec.ramp_down_mw, stop(t): -spec.shutdown_ramp_mw},
                ub=0.0,
            )
        add({start(t): 1.0, stop(t): 1.0}, ub=1.0)

        up_start = max(0, t - spec.min_up_hours + 1)
        add(
            {**{start(k): 1.0 for k in range(up_start, t+1)}, u(t): -1.0},
            ub=0.0,
        )
        down_start = max(0, t - spec.min_down_hours + 1)
        add(
            {**{stop(k): 1.0 for k in range(down_start, t+1)}, u(t): 1.0},
            ub=1.0,
        )

        if spec.initial_on and t < max(0, spec.min_up_hours - spec.initial_state_hours):
            add({u(t): 1.0}, lb=1.0, ub=1.0)
        if not spec.initial_on and t < max(0, spec.min_down_hours - spec.initial_state_hours):
            add({u(t): 1.0}, lb=0.0, ub=0.0)

        if mode == "complete":
            if t + spec.min_up_hours > HOURS:
                add({start(t): 1.0}, ub=0.0)
            if t + spec.min_down_hours > HOURS:
                add({stop(t): 1.0}, ub=0.0)

    matrix = lil_matrix((len(rows), size), dtype=float)
    for idx, coefficients in enumerate(rows):
        for col, value in coefficients.items():
            matrix[idx, col] = value

    result = milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(
            matrix.tocsr(), np.asarray(lower_rows), np.asarray(upper_rows)
        ),
        options={"time_limit": time_limit_seconds, "mip_rel_gap": 1e-7},
    )
    if result.status != 0 or result.x is None:
        raise CommitmentSolveError(
            f"Unit commitment did not solve to optimality (status {result.status}): "
            f"{result.message}"
        )
    hours: list[DispatchHour] = []
    for t in range(HOURS):
        power = max(0.0, float(result.x[p(t)]))
        on = bool(result.x[u(t)] > 0.5)
        started = bool(result.x[start(t)] > 0.5)
        stopped = bool(result.x[stop(t)] > 0.5)
        energy_margin = (prices[t] - energy_cost_per_mwh) * power
        cost = spec.startup_cost * started + spec.shutdown_cost * stopped
        hours.append(
            DispatchHour(
                period=t+1,
                online=on,
                power_mw=power,
                started=started,
                stopped=stopped,
                forecast_price=prices[t],
                energy_margin=energy_margin,
                transition_cost=cost,
                net_margin=energy_margin-cost,
            )
        )
    plan = tuple(hours)
    # This audit infers online state from positive power; when Pmin=0 a
    # committed zero-output hour is indistinguishable and is not audited here.
    if spec.min_mw > 0:
        check = audit_dispatch(
            spec, [h.power_mw for h in plan], terminal_mode=mode
        )
        if not check.feasible:
            raise CommitmentSolveError(
                "Solver output failed independent physical audit: "
                + "; ".join(check.violations)
            )

    # Explicitly report when the final commitment state must carry over.
    final_on = plan[-1].online
    suffix = 0
    for h in reversed(plan):
        if h.online != final_on:
            break
        suffix += 1
    carried = (
        (spec.min_up_hours if final_on else spec.min_down_hours) - suffix
    )
    if not any(h.started or h.stopped for h in plan):
        # Initial history also counts toward the uninterrupted terminal run.
        carried -= spec.initial_state_hours
    return CommitmentPlan(
        unit_id=spec.unit_id,
        hourly=plan,
        forecast_source=forecast_source,
        total_energy_mwh=sum(h.power_mw for h in plan),
        gross_margin=sum(h.energy_margin for h in plan),
        transition_cost=sum(h.transition_cost for h in plan),
        net_margin=sum(h.net_margin for h in plan),
        terminal_mode=mode,
        remaining_required_hours=max(0, carried),
    )
