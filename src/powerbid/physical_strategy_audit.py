"""Read-only physical screening of local market strategy simulation outcomes.

This is a diagnostic, NOT physical market re-clearing. It can invalidate an
unconstrained surrogate dispatch, but cannot repair it or establish PMSS
feasibility. It NEVER writes to or calls the teacher platform.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from powerbid.strategy_lab import StrategyResult
from powerbid.unit_commitment import TerminalMode, ThermalConstraints, audit_dispatch


@dataclass(frozen=True, slots=True)
class PhysicalStrategyAudit:
    strategy_name: str
    scenario_count: int
    physically_feasible_probability: float
    physically_feasible_count: int
    sample_violations: tuple[str, ...]
    proxy_score: float


def screen_strategy_results(
    strategies: Sequence[StrategyResult],
    physical: ThermalConstraints,
    *,
    terminal_mode: TerminalMode = "carryover",
    maximum_examples: int = 5,
) -> tuple[PhysicalStrategyAudit, ...]:
    """Screen each scenario's 24h *local surrogate accepted dispatch*.

    Feasibility is necessary, not sufficient: PMSS network constraints,
    settlement, and other units' physical limits are not analyzed.
    """
    if maximum_examples < 0:
        raise ValueError("maximum_examples cannot be negative")
    reports: list[PhysicalStrategyAudit] = []
    for result in strategies:
        feasible_weight = 0.0
        feasible_count = 0
        examples: list[str] = []
        for scenario in result.scenarios:
            if len(scenario.hours) != 24:
                raise ValueError("Each market outcome needs 24 hourly dispatches")
            audit = audit_dispatch(
                physical,
                [h.accepted_mw for h in scenario.hours],
                terminal_mode=terminal_mode,
            )
            if audit.feasible and scenario.feasible:
                feasible_count += 1
                feasible_weight += scenario.probability
            elif len(examples) < maximum_examples:
                if not scenario.feasible:
                    examples.append(f"{scenario.name}: market demand infeasible")
                for message in audit.violations:
                    if len(examples) >= maximum_examples:
                        break
                    examples.append(f"{scenario.name}: {message}")
        reports.append(
            PhysicalStrategyAudit(
                strategy_name=result.name,
                scenario_count=len(result.scenarios),
                physically_feasible_probability=min(1.0, feasible_weight),
                physically_feasible_count=feasible_count,
                sample_violations=tuple(examples),
                proxy_score=result.score,
            )
        )
    return tuple(reports)


def best_physical_candidate(
    audits: Sequence[PhysicalStrategyAudit],
) -> PhysicalStrategyAudit | None:
    """Return top proxy-scoring candidate IF it passes all physical scenarios."""
    eligible = [
        a for a in audits if a.physically_feasible_probability >= 1.0 - 1e-12
    ]
    return max(eligible, key=lambda a: a.proxy_score) if eligible else None
