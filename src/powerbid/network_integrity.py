"""Independent post-solve checks for the existing lossless DC network engines.

Checks MW conservation, directional thermal limits and Kirchhoff voltage-law
consistency (including cycles). These prove consistency with the *supplied*
DC equations only: they cannot establish the PMSS x-unit, MVA base, AC losses,
transformer tap/phase-shift model, or actual SCUC/SCED clearing.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

from powerbid.network_dispatch import DcNetwork


class DcPhysicsError(ValueError):
    """Dispatch contradicts the declared lossless DC grid or MW limits."""


@dataclass(frozen=True, slots=True)
class DcPhysicsAudit:
    period: int
    max_balance_error_mw: float
    max_flow_equation_error_mw: float
    tolerance_mw: float


def audit_dc_solution(
    network: DcNetwork,
    generation_mw: Mapping[str, float],
    flows_mw: Mapping[str, float],
    period: int,
    *,
    load_multiplier: float = 1.0,
) -> DcPhysicsAudit:
    """Check the exact original IDs and lossless DC flow equations.

    Reconstruct bus angles from a spanning tree, then test every branch,
    including non-tree branches; this detects unphysical circulating flows
    which can satisfy nodal balance and line ratings but violate DC KVL.
    The angle values are only mathematical coordinates on the supplied base.
    """
    if type(period) is not int or not 1 <= period <= 24:
        raise ValueError("period must be an integer in 1..24")
    if type(load_multiplier) not in (int, float) or not isfinite(load_multiplier) or load_multiplier <= 0:
        raise ValueError("load_multiplier must be finite and positive")
    if set(generation_mw) != set(network.unit_bus):
        raise DcPhysicsError("Generator IDs do not match DC unitBus")
    if set(flows_mw) != {line.line_id for line in network.lines}:
        raise DcPhysicsError("Line IDs do not match DC topology")
    if any(
        type(value) not in (int, float) or not isfinite(value)
        for value in (*generation_mw.values(), *flows_mw.values())
    ):
        raise DcPhysicsError("DC dispatch includes nonfinite or nonnumeric MW")
    load = {
        bus: network.hourly_demand_mw[bus][period - 1] * load_multiplier
        for bus in network.buses
    }
    scale = max(1.0, sum(load.values()))
    tolerance = max(1e-4, 1e-8 * scale)
    if any(power < -tolerance for power in generation_mw.values()):
        raise DcPhysicsError("DC generation cannot be negative")

    # generation + imports - exports - load = 0 at each individual bus.
    balance = {bus: -demand for bus, demand in load.items()}
    for unit, value in generation_mw.items():
        balance[network.unit_bus[unit]] += value
    neighbors: dict[str, list[tuple[str, float]]] = {
        bus: [] for bus in network.buses
    }
    for line in network.lines:
        value = flows_mw[line.line_id]
        if abs(value) > line.limit_mw + tolerance:
            raise DcPhysicsError(f"Line {line.line_id} exceeds its thermal MW limit")
        balance[line.from_bus] -= value
        balance[line.to_bus] += value
        # theta_from - theta_to = f*x/baseMva, with f signed from->to.
        delta = value * line.reactance_pu / network.base_mva
        neighbors[line.from_bus].append((line.to_bus, -delta))
        neighbors[line.to_bus].append((line.from_bus, delta))
    max_balance = max(abs(value) for value in balance.values())
    if max_balance > tolerance:
        raise DcPhysicsError(
            f"DC nodal power balance violated (max residual {max_balance:.6g} MW)"
        )

    angles = {network.slack_bus: 0.0}
    queue = [network.slack_bus]
    for bus in queue:
        for neighbor, delta in neighbors[bus]:
            if neighbor not in angles:
                angles[neighbor] = angles[bus] + delta
                queue.append(neighbor)
    if len(angles) != len(network.buses):
        raise DcPhysicsError("DC network contains an unconnected bus")
    max_flow_error = max(
        (
            abs(
                (angles[line.from_bus] - angles[line.to_bus])
                * network.base_mva / line.reactance_pu
                - flows_mw[line.line_id]
            )
            for line in network.lines
        ),
        default=0.0,
    )
    if max_flow_error > tolerance:
        raise DcPhysicsError(
            "DC voltage-angle/loop consistency violated "
            f"(max flow residual {max_flow_error:.6g} MW)"
        )
    return DcPhysicsAudit(period, max_balance, max_flow_error, tolerance)
