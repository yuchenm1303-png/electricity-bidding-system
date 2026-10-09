"""Trace the *gaps*, not fabricated readiness, from anonymous PMSS evidence.

Existing observations are aggregate, read-only sources. They never contain a
certified 1:1 binding of scenario machine, operating state, physical time and
cost units to our ThermalConstraints fields. This file deliberately provides
a conservative 13-field action list without creating model parameters.

Presence does NOT mean semantics, identity mapping, or UC readiness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from powerbid.pmss_integration import PMSSSnapshot
from powerbid.pmss_physical_lineage import FIELD_UNITS
from powerbid.pmss_scene_constraint_evidence import validate_scene_constraint_evidence
from powerbid.pmss_technical_evidence import validate_client_technical_evidence

Status = Literal[
    "NO_FIELD_OBSERVATION",
    "PARTIAL_ANONYMOUS_OBSERVATION",
    "ANONYMOUS_OBSERVATION_NOT_VERIFIED",
]
# Source fields below are *hypotheses* based on known names, NOT physical
# equivalences. A teacher document or code-level rule must establish each.
TECHNICAL_FIELD_HINTS = {
    "min_mw": "minCapacity",
    "max_mw": "pdAdjustMax",
    "ramp_up_mw": "incRate",
    "ramp_down_mw": "decRate",
    "min_up_hours": "minOnTime",
    "min_down_hours": "minOffTime",
    "startup_cost": "launchCost",
}
INITIAL_FIELD_HINTS = {
    "initial_on": "initialState",
    "initial_mw": "power",
    "initial_state_hours": "keepTime",
}
SCENE_SWITCH_HINTS = {
    "ramp_up_mw": "ifConRamp",
    "ramp_down_mw": "ifConRamp",
    "min_up_hours": "ifConMinOnOffTm",
    "min_down_hours": "ifConMinOnOffTm",
    "startup_cost": "ifConStartCost",
    "initial_mw": "ifConInitPower",
    "initial_on": "ifConInitPower",
}
# These describe needed *investigation*, not approved conversions.
TASKS = {
    "min_mw": "核实机组物理最小稳定出力、单位和是否适用于当前场景",
    "max_mw": "核实机组实际运行最大出力与可申报容量的区别",
    "ramp_up_mw": "核实 incRate 的物理单位、时间基准与约束是否生效",
    "ramp_down_mw": "核实 decRate 的物理单位、时间基准与约束是否生效",
    "startup_ramp_mw": "获取启动转换期间可达到的MW及明确的时间定义",
    "shutdown_ramp_mw": "获取停机转换期间可达到的MW及明确的时间定义",
    "min_up_hours": "核实最短连续开机的实际单位及0值与约束开关语义",
    "min_down_hours": "核实最短连续停机的实际单位及0值与约束开关语义",
    "startup_cost": "核实启动费用口径、币种/报价成本单位及是否生效",
    "shutdown_cost": "获取并核实停机费用和计价口径（不得默认0）",
    "initial_on": "按机组ID核实初始状态编码、对应日期及是否已投运",
    "initial_mw": "按机组ID核实前一时段实际出力MW及约束是否启用",
    "initial_state_hours": "核实初始状态持续时间及其小时换算依据",
}


@dataclass(frozen=True, slots=True)
class FieldEvidenceGap:
    field: str
    model_unit: str
    observed_source_field: str | None
    observed_source_kind: str | None
    aggregate_values_present: int
    aggregate_rows_reported: int
    status: Status
    relevant_switch_name_unverified: str | None
    relevant_switch_value_1: int | None
    relevant_switch_value_0: int | None
    required_next_evidence: str
    semantically_verified: bool = False
    linked_to_individual_generator: bool = False
    usable_as_model_input: bool = False


@dataclass(frozen=True, slots=True)
class UCPhysicalEvidenceGapReport:
    unit_count: int
    fields_required_per_unit: int
    fields_with_any_anonymous_observations: int
    fields_missing_observations: int
    individually_verified_fields: int
    independent_technical_parameters_ready: bool
    scenario_switch_codes_interpreted: bool
    generator_initial_states_confirmed: bool
    fields: tuple[FieldEvidenceGap, ...]
    verdict: str = "BLOCKED_INDEPENDENT_PMSS_PHYSICAL_UC"
    disclaimer: str = (
        "This is a read-only source GAP report, NOT a percentage of "
        "physics validated. Untrusted anonymous counts and code 0/1 "
        "cannot prove machine identity, constraint activation, MW/h "
        "time base, pricing units, or real PMSS dispatch rules."
    )


def audit_pmss_uc_evidence_gaps(
    snapshot: PMSSSnapshot,
    *,
    technical_evidence: Any = None,
    scene_constraint_evidence: Any = None,
) -> UCPhysicalEvidenceGapReport:
    """Return a safe, static source map and remaining physical proof actions.

    Input source summaries are fully revalidated; neither raw PMSS unit rows
    nor uploaded per-unit claims are included in the response.
    """
    technical = (
        validate_client_technical_evidence(technical_evidence, snapshot=snapshot)
        if technical_evidence is not None else None
    )
    scene = (
        validate_scene_constraint_evidence(
            scene_constraint_evidence, expected_units=len(snapshot.units)
        )
        if scene_constraint_evidence is not None else None
    )
    reports: list[FieldEvidenceGap] = []
    for field, unit in FIELD_UNITS.items():
        source_name: str | None = None
        kind: str | None = None
        count = 0
        total = 0
        if field in TECHNICAL_FIELD_HINTS:
            source_name = TECHNICAL_FIELD_HINTS[field]
            kind = "anonymous_pmss_generator_column"
            if technical is not None:
                stat = technical["observed_fields"][source_name]
                count = stat["present"]
                total = technical["unit_count"]
        elif field in INITIAL_FIELD_HINTS:
            source_name = INITIAL_FIELD_HINTS[field]
            kind = "anonymous_pmss_initial_state_column"
            if scene is not None:
                stat = scene["initial_fields"][source_name]
                count = stat["present"]
                total = scene["initial_rows"]

        if count == 0:
            status: Status = "NO_FIELD_OBSERVATION"
        elif count < total:
            status = "PARTIAL_ANONYMOUS_OBSERVATION"
        else:
            status = "ANONYMOUS_OBSERVATION_NOT_VERIFIED"

        switch_name = SCENE_SWITCH_HINTS.get(field)
        switch_stat = (
            scene["switches"][switch_name]
            if scene is not None and switch_name is not None else None
        )
        reports.append(FieldEvidenceGap(
            field=field,
            model_unit=unit,
            observed_source_field=source_name,
            observed_source_kind=kind,
            aggregate_values_present=count,
            aggregate_rows_reported=total,
            status=status,
            relevant_switch_name_unverified=switch_name,
            relevant_switch_value_1=(
                switch_stat["value_1"] if switch_stat is not None else None
            ),
            relevant_switch_value_0=(
                switch_stat["value_0"] if switch_stat is not None else None
            ),
            required_next_evidence=TASKS[field],
        ))
    present = sum(item.aggregate_values_present > 0 for item in reports)
    return UCPhysicalEvidenceGapReport(
        unit_count=len(snapshot.units),
        fields_required_per_unit=len(FIELD_UNITS),
        fields_with_any_anonymous_observations=present,
        fields_missing_observations=len(FIELD_UNITS) - present,
        individually_verified_fields=0,
        independent_technical_parameters_ready=False,
        scenario_switch_codes_interpreted=False,
        generator_initial_states_confirmed=False,
        fields=tuple(reports),
    )
