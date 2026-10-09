"""Compare historical bid-dispatch errors against fixed-observed-injection DC flow.

Two different questions:
(A) How far do *newly re-cleared original bids* differ from PMSS branch MW?
(B) If actual PMSS generator dispatch is held fixed, how far does DC load flow
    differ from PMSS branch MW?

(B) diagnoses the network model *conditional on true historical dispatch*.
It is not a valid forecast/counterfactual of new bids and cannot by itself
identify the exact source of A's greater error.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from powerbid.fixed_injection_diagnostics import (
    FixedInjectionReport,
    replay_observed_injections,
)
from powerbid.historical_validation import DayValidation, validate_historical_day
from powerbid.network_dispatch import network_from_dict


@dataclass(frozen=True, slots=True)
class FlowErrorAttribution:
    case_date: str
    independent_dispatch_flow_mae_mw: float | None
    observed_dispatch_flow_mae_mw: float | None
    same_observation_set: bool
    absolute_mae_difference_mw: float | None
    remaining_error_ratio: float | None
    observed_line_points: int
    original_model_line_points: int
    missing_dispatch_hours: int
    unbalanced_dispatch_hours: int
    explanation: str = (
        "Original-bid DC re-clearing vs fixed-observed-generator-injection DC flow. "
        "Difference is a diagnostic, NOT a causal decomposition, candidate-bid "
        "PMSS confirmation, or an actual profit improvement."
    )


@dataclass(frozen=True, slots=True)
class FlowAttributionReport:
    comparison: FlowErrorAttribution
    independent_dispatch: DayValidation
    observed_dispatch: FixedInjectionReport


def compare_dispatch_and_network_sources(
    raw: dict[str, Any],
) -> FlowAttributionReport:
    """Read-only diagnostics on one verified and complete historical snapshot."""
    ordinary = validate_historical_day(raw)
    network = network_from_dict(raw["dcNetwork"])
    replayed = replay_observed_injections(
        network, raw["results"], case_date=ordinary.case_date
    )
    same_points = (
        replayed.modeled_hours == 24
        and replayed.missing_injection_hours == 0
        and replayed.unbalanced_injection_hours == 0
        and replayed.observed_line_points == ordinary.line_flow_abs.observed_points
        and ordinary.line_flow_abs.observed_points > 0
    )
    ordinary_mae = ordinary.line_flow_abs.mae
    conditioned_mae = replayed.flow_magnitude_mae_mw
    difference = (
        ordinary_mae - conditioned_mae
        if same_points and ordinary_mae is not None and conditioned_mae is not None
        else None
    )
    ratio = (
        conditioned_mae / ordinary_mae
        if difference is not None and ordinary_mae > 1e-10
        else None
    )
    return FlowAttributionReport(
        comparison=FlowErrorAttribution(
            case_date=ordinary.case_date,
            independent_dispatch_flow_mae_mw=ordinary_mae,
            observed_dispatch_flow_mae_mw=conditioned_mae,
            same_observation_set=same_points,
            absolute_mae_difference_mw=difference,
            remaining_error_ratio=ratio,
            observed_line_points=replayed.observed_line_points,
            original_model_line_points=ordinary.line_flow_abs.observed_points,
            missing_dispatch_hours=replayed.missing_injection_hours,
            unbalanced_dispatch_hours=replayed.unbalanced_injection_hours,
        ),
        independent_dispatch=ordinary,
        observed_dispatch=replayed,
    )
