"""Fail-closed technical-input gate for offline 24h network + commitment research.

Do not infer unknown commitment/ramping data from historic PMSS bids,
generation capacity or observed dispatch. Synthetic source is NOT real PMSS.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

from powerbid.joint_strategy import evaluate_joint_bid
from powerbid.network_dispatch import DcNetwork
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_bid_rule_safety import validate_new_curve
from powerbid.pmss_integration import PMSSSnapshot, curve_for_period
from powerbid.strategy_lab import BidPolicy, DemandStress, generate_policy_plan
from powerbid.unit_commitment import ThermalConstraints

FIELDS = frozenset(ThermalConstraints.__dataclass_fields__)
SOURCES = frozenset({"course_verified_by_user", "synthetic", "user_supplied_unverified"})


@dataclass(frozen=True, slots=True)
class JointReadiness:
    ready: bool
    total_units: int
    supplied_units: int
    missing_unit_ids: tuple[str, ...]
    unexpected_unit_ids: tuple[str, ...]
    invalid: dict[str, str]
    source: str
    independently_verified: bool = False
    message: str = (
        "Data complete for local simulation does NOT certify PMSS technical "
        "parameters, market clearing, or suitability for actual bids."
    )


@dataclass(frozen=True, slots=True)
class JointCandidate:
    name: str
    model_score: float
    expected_net_margin: float
    accepted_mwh: float
    start_count: int
    stop_count: int
    segments: tuple[tuple[float, float, float], ...]
    dispatch_24h: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class JointStudy:
    target_unit_id: str
    ranked: tuple[JointCandidate, ...]
    top_candidate: JointCandidate
    readiness: JointReadiness
    technical_source_description: str
    terminal_mode: str
    model: str = "Integrated 24h DC+UC MILP with fixed-commitment LP nodal prices"
    safe_for_live_submission: bool = False
    validated_against_pmss: bool = False
    pmss_write_performed: bool = False
    pmss_clearing_executed: bool = False


def _spec(unit_id: str, data: Mapping[str, Any]) -> ThermalConstraints:
    if set(data) != FIELDS or data.get("unit_id") != unit_id:
        raise ValueError("exact technical field set and matching unit_id required")
    if type(data["initial_on"]) is not bool:
        raise ValueError("initial_on must be Boolean, not a guessed state")
    floats = (
        "min_mw", "max_mw", "ramp_up_mw", "ramp_down_mw",
        "startup_ramp_mw", "shutdown_ramp_mw",
        "startup_cost", "shutdown_cost", "initial_mw",
    )
    integers = ("min_up_hours", "min_down_hours", "initial_state_hours")
    for field in floats:
        value = data[field]
        if type(value) not in (int, float) or not isfinite(value):
            raise ValueError(f"{field} must be a finite numeric input")
    for field in integers:
        value = data[field]
        if type(value) is not int or not 1 <= value <= 10000:
            raise ValueError(f"{field} must be a positive integer")
    return ThermalConstraints(**data)


def assess_joint_readiness(
    snapshot: PMSSSnapshot,
    records: Mapping[str, Any] | None,
    *,
    source: str = "",
) -> JointReadiness:
    """Check all generator parameters are present without inserting defaults."""
    if records is not None and not isinstance(records, Mapping):
        raise ValueError("Technical records must be keyed by PMSS generator ID")
    records = {} if records is None else records
    expected = {unit.unit_id for unit in snapshot.units}
    missing = tuple(sorted(expected - set(records)))
    unknown = tuple(sorted(set(records) - expected))
    invalid: dict[str, str] = {}
    for unit in snapshot.units:
        raw = records.get(unit.unit_id)
        if raw is None:
            continue
        try:
            if not isinstance(raw, Mapping):
                raise ValueError("Technical record must be an object")
            spec = _spec(unit.unit_id, raw)
            if spec.max_mw > unit.capacity_mw + 1e-7:
                raise ValueError("technical max exceeds declared capacity")
            if spec.min_mw + 1e-7 < unit.min_power_mw:
                raise ValueError("technical min lower than PMSS minimum")
            for period in snapshot.bids[unit.unit_id]:
                if period.segments[-1].end_power > spec.max_mw + 1e-7:
                    raise ValueError("original offered maximum exceeds technical max")
        except (ValueError, TypeError) as exc:
            invalid[unit.unit_id] = str(exc)
    return JointReadiness(
        ready=(source in SOURCES and not missing and not unknown and not invalid),
        total_units=len(expected),
        supplied_units=len(expected & set(records)),
        missing_unit_ids=missing,
        unexpected_unit_ids=unknown,
        invalid=invalid,
        source=source,
    )


def compare_joint_legal_candidates(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    technical: Mapping[str, Any],
    target_unit_id: str,
    *,
    technical_source: str,
    technical_source_description: str,
    policies: Sequence[BidPolicy] | None = None,
    terminal_mode: str = "carryover",
    solver_timeout_seconds: float = 12.0,
) -> JointStudy:
    """Local MILP: at most three NEW rule-legal bids; no PMSS execution."""
    verify_network_inputs(snapshot, network, target_unit_id)
    if not technical_source_description.strip() or len(technical_source_description) > 500:
        raise ValueError("Explicit technical-data source description required")
    if terminal_mode not in ("carryover", "complete"):
        raise ValueError("Unsupported terminal mode")
    if type(solver_timeout_seconds) not in (int, float) or not 1 <= solver_timeout_seconds <= 30:
        raise ValueError("Solver timeout must be within 1..30 seconds")
    report = assess_joint_readiness(snapshot, technical, source=technical_source)
    if not report.ready:
        raise ValueError(
            "Joint MILP blocked: missing, invalid, or unprovenanced generator "
            "parameters; " + repr(asdict(report))[:900]
        )
    specs = {ident: _spec(ident, value) for ident, value in technical.items()}
    selected = tuple(policies) if policies is not None else (
        BidPolicy("成本报价", markup=0),
        BidPolicy("成本加价20", markup=20),
    )
    if not 1 <= len(selected) <= 3 or len({x.name for x in selected}) != len(selected):
        raise ValueError("Provide 1..3 distinct legal candidate policies")
    results = []
    for policy in selected:
        plan = generate_policy_plan(snapshot, target_unit_id, policy)
        for period in plan:
            validate_new_curve(snapshot, target_unit_id, period.segments)
        evaluated = evaluate_joint_bid(
            snapshot, network, specs, target_unit_id, policy.name, plan,
            (DemandStress("neutral synthetic scenario"),),
            terminal_mode=terminal_mode,
            solver_time_limit_seconds=solver_timeout_seconds,
            tail_fraction=1.0,
        )
        market = evaluated.scenarios[0].market
        blocks = curve_for_period(evaluated.periods, 1)
        results.append(JointCandidate(
            name=policy.name,
            model_score=float(evaluated.risk_score),
            expected_net_margin=float(evaluated.expected_net_profit),
            accepted_mwh=float(evaluated.expected_accepted_mwh),
            start_count=int(sum(bool(hour.unit_started[target_unit_id]) for hour in market.hours)),
            stop_count=int(sum(bool(hour.unit_stopped[target_unit_id]) for hour in market.hours)),
            segments=tuple(
                (seg.start_power, seg.end_power, seg.price) for seg in blocks
            ),
            dispatch_24h=tuple(
                float(hour.accepted_by_unit[target_unit_id]) for hour in market.hours
            ),
        ))
    ranked = tuple(sorted(results, key=lambda x: (-x.model_score, x.name)))
    return JointStudy(
        target_unit_id=target_unit_id,
        ranked=ranked,
        top_candidate=ranked[0],
        readiness=report,
        technical_source_description=technical_source_description,
        terminal_mode=terminal_mode,
    )
