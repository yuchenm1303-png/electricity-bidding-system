"""Independent hourly physical schedule audit for the existing 24h DC+UC MILP.

Uses explicit on/start/stop statuses (not MW>0 heuristics), so zero-Pmin
online units are handled correctly. This validates local model equations,
not real PMSS startup/ramp semantics or actual commitment.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite

from powerbid.unit_commitment import TerminalMode, ThermalConstraints


class JointPhysicsError(ValueError):
    """An optimized UC schedule does not satisfy declared technical limits."""


def audit_joint_schedule(
    technical: Mapping[str, ThermalConstraints],
    hours: Sequence[object],
    *,
    terminal_mode: TerminalMode,
) -> None:
    """Check the optimizer's MW and binary statuses across all 24 periods."""
    if terminal_mode not in ("complete", "carryover") or len(hours) != 24:
        raise ValueError("A valid terminal mode and exactly 24 hours are required")
    units = set(technical)
    for hour in hours:
        for field in ("accepted_by_unit", "unit_online", "unit_started", "unit_stopped"):
            value = getattr(hour, field)
            if set(value) != units:
                raise JointPhysicsError("Hourly UC generator IDs are incomplete")
    for unit_id, spec in technical.items():
        previous_on = spec.initial_on
        previous_mw = spec.initial_mw
        elapsed = spec.initial_state_hours
        tol = max(1e-4, 1e-7 * spec.max_mw)
        for index, hour in enumerate(hours, 1):
            mw = hour.accepted_by_unit[unit_id]
            on = hour.unit_online[unit_id]
            started = hour.unit_started[unit_id]
            stopped = hour.unit_stopped[unit_id]
            if (
                type(mw) not in (int, float) or not isfinite(mw)
                or type(on) is not bool or type(started) is not bool
                or type(stopped) is not bool
            ):
                raise JointPhysicsError("Invalid hourly physical MW or UC status")
            if started != (on and not previous_on) or stopped != (previous_on and not on):
                raise JointPhysicsError(f"Hour {index}: inconsistent UC transition for {unit_id}")
            if mw < -tol or mw > spec.max_mw + tol:
                raise JointPhysicsError(f"Hour {index}: generator {unit_id} outside power bounds")
            if on and mw < spec.min_mw - tol:
                raise JointPhysicsError(f"Hour {index}: generator {unit_id} below online minimum")
            if not on and abs(mw) > tol:
                raise JointPhysicsError(f"Hour {index}: offline generator {unit_id} produces MW")
            if started or stopped:
                required = spec.min_up_hours if previous_on else spec.min_down_hours
                if elapsed < required:
                    raise JointPhysicsError(
                        f"Hour {index}: {unit_id} violates minimum state duration"
                    )
                if started and mw > spec.startup_ramp_mw + tol:
                    raise JointPhysicsError(f"Hour {index}: {unit_id} violates startup ramp")
                if stopped and previous_mw > spec.shutdown_ramp_mw + tol:
                    raise JointPhysicsError(f"Hour {index}: {unit_id} violates shutdown ramp")
                elapsed = 1
            else:
                if on and mw - previous_mw > spec.ramp_up_mw + tol:
                    raise JointPhysicsError(f"Hour {index}: {unit_id} violates upward ramp")
                if on and previous_mw - mw > spec.ramp_down_mw + tol:
                    raise JointPhysicsError(f"Hour {index}: {unit_id} violates downward ramp")
                elapsed += 1
            previous_on, previous_mw = on, mw
        if terminal_mode == "complete":
            required = spec.min_up_hours if previous_on else spec.min_down_hours
            if elapsed < required:
                raise JointPhysicsError(f"Terminal state for {unit_id} violates minimum hours")
