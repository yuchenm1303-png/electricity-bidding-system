"""Fetch and attach same-case PMSS SCENE EVIDENCE via approved READ routes only.

This function uses existing approved TeacherPlatformAdapter read methods.
Project ID and case date are explicit requirements: NEVER use a guessed first
project/case, and never infer physical UC parameters from anonymous rows.

The authorized online query does not independently establish field semantics,
units, machine identity, or PMSS SCUC rules. Source association is still
labelled as a query-origin/selection attestation, not a platform signature.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Protocol

from powerbid.pmss_evidence_attachment import attach_pmss_evidence
from powerbid.pmss_integration import snapshot_from_pmss
from powerbid.pmss_scene_constraint_evidence import (
    summarize_scene_constraint_evidence,
)


class SceneReadClient(Protocol):
    def get_context(self, project_id: str) -> Any: ...
    def get_scene_unit_constraints(
        self, *, scene_id: str, page_no: int, page_size: int
    ) -> dict[str, Any]: ...
    def get_unit_initial_state_inputs(
        self,
        *,
        scene_id: str,
        project_id: str,
        case_id: str,
        page_no: int,
        page_size: int,
    ) -> dict[str, Any]: ...


def _case_date(raw: Any) -> str:
    if type(raw) is not str or len(raw) != 10:
        raise ValueError("PMSS case date must be exactly YYYY-MM-DD")
    try:
        if date.fromisoformat(raw).isoformat() != raw:
            raise ValueError("PMSS case date not canonical")
    except ValueError as exc:
        raise ValueError("PMSS case date must be exactly YYYY-MM-DD") from exc
    return raw


def _ident(raw: Any, label: str) -> str:
    if type(raw) is not str or not raw or len(raw) > 128:
        raise ValueError(f"{label} must be a nonempty bounded identifier")
    # These values are never interpolated into URLs or printed, but block
    # accidental whitespace, log characters and query-parameter fragments.
    if any(not (ch.isalnum() or ch in "._-") for ch in raw):
        raise ValueError(f"{label} contains invalid identifier characters")
    return raw


def collect_same_case_scene_evidence(
    client: SceneReadClient,
    historical: Mapping[str, Any],
    *,
    project_id: str,
    case_date: str,
) -> dict[str, Any]:
    """Create a new sanitized snapshot; cannot save or execute any PMSS bid.

    Fail closed on a missing or ambiguous project/case, missing safe IDs, a
    truncated page, empty source, or an incorrect snapshot case date.
    Requests: get_context() read operations, then exactly two approved read
    methods for the selected case (a read-only POST and a GET).
    """
    project_id = _ident(project_id, "Explicit project ID")
    case_date = _case_date(case_date)
    if not isinstance(historical, Mapping) or (
        historical.get("historicalBacktestOnly") is not True
        or historical.get("caseDate") != case_date
        or "dcNetwork" not in historical
    ):
        raise ValueError("Historical snapshot must have the matching case date and DC grid")
    if historical.get("evidenceBinding") is not None or (
        historical.get("sceneConstraintEvidence") is not None
    ):
        raise ValueError("Already-attached scene evidence must never be replaced")
    # Check local market identity and completeness BEFORE any online request.
    market = snapshot_from_pmss(
        unit_tree=historical["unitTree"],
        unit_bids=historical["unitBids"],
        market_system=historical["marketSystem"],
        demand_forecast_mw=historical["demandForecastMw"],
        forecast_source=historical["forecastSource"],
    )
    if not 1 <= len(market.units) <= 30:
        raise ValueError("Unsupported historical generator count")

    context = client.get_context(project_id)
    if not isinstance(context.project, Mapping) or (
        context.project.get("projectId") != project_id
    ):
        raise ValueError("PMSS context does not match the explicitly selected project")
    matching = [
        item for item in context.cases
        if isinstance(item, Mapping) and item.get("caseDate") == case_date
    ]
    if len(matching) != 1:
        raise ValueError("Expected exactly one explicit matching PMSS case and date")
    case = matching[0]
    scene_id = _ident(case.get("pmSceneId"), "Case scenario ID")
    case_id = _ident(case.get("caseId"), "Case ID")

    calculation = client.get_scene_unit_constraints(
        scene_id=scene_id, page_no=1, page_size=999
    )
    initial = client.get_unit_initial_state_inputs(
        scene_id=scene_id, project_id=project_id,
        case_id=case_id, page_no=1, page_size=999
    )
    summary = summarize_scene_constraint_evidence(
        calculation, initial, expected_units=len(market.units)
    )
    if summary["constraintRows"] < 1 or summary["initialRows"] < 1:
        raise ValueError("PMSS scene or initial-state query returned no rows")
    # Legacy summary format does not contain a signed case ID. Even though
    # these queries used the explicitly selected case, do NOT falsely claim
    # independent platform authentication or verified numerical semantics.
    return attach_pmss_evidence(
        historical,
        scene_summary=summary,
        scene_case_date=case_date,
        scene_source_note=(
            "Authorized same-case PMSS read-only scenario queries; case "
            "selection verified by operator workflow, NOT signed provenance"
        ),
    )
