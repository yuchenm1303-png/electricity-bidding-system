"""Case-bound *integrity*, not authenticity, for offline PMSS evidence attachments.

The historical PMSS scene-summary format contains no actual case identity.
An operator must explicitly attest which case it belongs to. The SHA256
ledger detects subsequent mismatched-file edits, but cannot independently
verify teacher-platform source authenticity or field semantics.

Do not turn anonymous statistics into generator-specific UC parameters.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
from hashlib import sha256
from typing import Any

from powerbid.network_dispatch import network_from_dict
from powerbid.network_strategy import verify_network_inputs
from powerbid.pmss_integration import snapshot_from_pmss
from powerbid.pmss_scene_constraint_evidence import validate_scene_constraint_evidence
from powerbid.pmss_technical_evidence import (
    sanitize_pmss_technical_evidence,
    validate_client_technical_evidence,
)

SNAPSHOT_KEYS = frozenset({
    "unitTree", "unitBids", "marketSystem", "demandForecastMw",
    "forecastSource", "historicalBacktestOnly", "caseDate",
    "results", "loadSourceKind", "loadNodeCount", "dcNetwork",
    "technicalEvidence", "sceneConstraintEvidence", "evidenceBinding",
})
SENSITIVE_PARTS = (
    "cookie", "token", "password", "passwd", "secret", "session",
    "authorization", "privatekey", "csrf",
)
BINDING_KEYS = frozenset({
    "schemaVersion", "caseDate", "technicalSha256", "sceneSha256",
    "technicalAssociation", "sceneAssociation",
    "sceneSourceNote", "independentlyVerified",
})


def _date(value: Any) -> str:
    if type(value) is not str or len(value) != 10:
        raise ValueError("Case date must be explicit ISO YYYY-MM-DD")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Invalid case date")
    except ValueError as exc:
        raise ValueError("Case date must be explicit ISO YYYY-MM-DD") from exc
    return value


def _digest(value: Any) -> str:
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _note(value: Any) -> str:
    if type(value) is not str or not 12 <= len(value.strip()) <= 220:
        raise ValueError("Scene case source note must have 12..220 characters")
    lower = value.lower().replace(" ", "")
    if any(term in lower for term in (*SENSITIVE_PARTS, "https://", "http://", "?")):
        raise ValueError("Scene note must not include secrets, URLs or query parameters")
    return value.strip()


def _screen_snapshot(raw: Any) -> None:
    if not isinstance(raw, dict) or set(raw) - SNAPSHOT_KEYS:
        raise ValueError("Snapshot has unknown fields; use the allowlisted PMSS exporter")
    nodes = [(raw, 0)]
    seen = 0
    while nodes:
        item, depth = nodes.pop()
        seen += 1
        if seen > 100_000 or depth > 14:
            raise ValueError("Snapshot exceeds safe complexity limits")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("Snapshot keys must be strings")
                lowered = key.lower().replace("-", "").replace("_", "")
                if any(word in lowered for word in SENSITIVE_PARTS):
                    raise ValueError("Snapshot includes credential-like keys")
                nodes.append((child, depth+1))
        elif isinstance(item, list):
            nodes.extend((x, depth+1) for x in item)


def verify_pmss_evidence_binding(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate attached digests and claimed date; no independent authentication."""
    binding = raw.get("evidenceBinding")
    if binding is None:
        return None  # legacy snapshots may remain usable but NOT case-bound
    if not isinstance(binding, dict) or set(binding) != BINDING_KEYS:
        raise ValueError("Invalid PMSS evidence binding schema")
    if type(binding["schemaVersion"]) is not int or binding["schemaVersion"] != 1:
        raise ValueError("Unknown PMSS evidence binding version")
    case_date = _date(raw.get("caseDate"))
    if binding["caseDate"] != case_date:
        raise ValueError("Evidence binding belongs to another PMSS case date")
    if binding["independentlyVerified"] is not False:
        raise ValueError("Evidence binding cannot assert platform verification")
    t = raw.get("technicalEvidence")
    s = raw.get("sceneConstraintEvidence")
    if binding["technicalAssociation"] not in (
        "exact_unit_id_join", "legacy_summary_only", "absent"
    ):
        raise ValueError("Unexpected technical source association")
    if binding["sceneAssociation"] not in (
        "operator_attested_case_date", "absent"
    ):
        raise ValueError("Unexpected scene source association")
    if (t is None) != (binding["technicalAssociation"] == "absent"):
        raise ValueError("Technical association and evidence content disagree")
    if (s is None) != (binding["sceneAssociation"] == "absent"):
        raise ValueError("Scene association and evidence content disagree")
    if (t is None and binding["technicalSha256"] is not None) or (
        t is not None and binding["technicalSha256"] != _digest(t)
    ):
        raise ValueError("Technical evidence digest differs from case binding")
    if (s is None and binding["sceneSha256"] is not None) or (
        s is not None and binding["sceneSha256"] != _digest(s)
    ):
        raise ValueError("Scene evidence digest differs from case binding")
    if s is None:
        if binding["sceneSourceNote"] is not None:
            raise ValueError("Absent scene evidence cannot carry a source note")
    else:
        _note(binding["sceneSourceNote"])
    return {
        "case_date": case_date,
        "technical_evidence_attached": t is not None,
        "technical_association": binding["technicalAssociation"],
        "scene_evidence_attached": s is not None,
        "scene_association": binding["sceneAssociation"],
        "content_digests_matched": True,
        "teacher_platform_source_authenticated": False,
        "teacher_physical_semantics_verified": False,
        "model_technical_parameters_verified": False,
        "notice": (
            "SHA256 binds unchanged anonymous summaries to this local snapshot. "
            "The scene date is OPERATOR ATTESTED and not platform verified; "
            "no UC parameter values or semantics are certified."
        ),
    }


def attach_pmss_evidence(
    raw_snapshot: Mapping[str, Any],
    *,
    private_grid: Mapping[str, Any] | None = None,
    scene_summary: Mapping[str, Any] | None = None,
    scene_case_date: str | None = None,
    scene_source_note: str | None = None,
) -> dict[str, Any]:
    """Create a NEW sanitized case-bound snapshot without changing input data."""
    _screen_snapshot(raw_snapshot)
    if raw_snapshot.get("historicalBacktestOnly") is not True:
        raise ValueError("Only explicitly historical, read-only PMSS inputs are accepted")
    case_date = _date(raw_snapshot.get("caseDate"))
    if raw_snapshot.get("evidenceBinding") is not None:
        raise ValueError("Snapshot already bound; refuse re-attestation or overwrite")
    if "dcNetwork" not in raw_snapshot:
        raise ValueError("Verified network must be present before evidence attachment")
    market = snapshot_from_pmss(
        unit_tree=raw_snapshot["unitTree"],
        unit_bids=raw_snapshot["unitBids"],
        market_system=raw_snapshot["marketSystem"],
        demand_forecast_mw=raw_snapshot["demandForecastMw"],
        forecast_source=raw_snapshot["forecastSource"],
    )
    network = network_from_dict(raw_snapshot["dcNetwork"])
    verify_network_inputs(market, network, market.units[0].unit_id)
    result = deepcopy(dict(raw_snapshot))
    if private_grid is not None:
        if result.get("technicalEvidence") is not None:
            raise ValueError("Snapshot already contains technical evidence; no replacement")
        result["technicalEvidence"] = sanitize_pmss_technical_evidence(
            private_grid, snapshot=market
        )
        technical_association = "exact_unit_id_join"
    elif result.get("technicalEvidence") is not None:
        validate_client_technical_evidence(result["technicalEvidence"], snapshot=market)
        technical_association = "legacy_summary_only"
    else:
        technical_association = "absent"

    if scene_summary is not None:
        if result.get("sceneConstraintEvidence") is not None:
            raise ValueError("Snapshot already contains scene evidence; no replacement")
        result["sceneConstraintEvidence"] = deepcopy(dict(scene_summary))
    if result.get("sceneConstraintEvidence") is not None:
        # The legacy scene summary has counts but NO case ID, so the
        # association is visibly an operator assertion and never authentic.
        if _date(scene_case_date) != case_date:
            raise ValueError("Scene evidence operator-attested date differs from case")
        note = _note(scene_source_note)
        validate_scene_constraint_evidence(
            result["sceneConstraintEvidence"], expected_units=len(market.units)
        )
        scene_association = "operator_attested_case_date"
    else:
        if scene_case_date is not None or scene_source_note is not None:
            raise ValueError("Do not associate missing scene evidence with a case")
        note = None
        scene_association = "absent"
    if technical_association == "absent" and scene_association == "absent":
        raise ValueError("Provide at least one authorized evidence source")
    result["evidenceBinding"] = {
        "schemaVersion": 1,
        "caseDate": case_date,
        "technicalSha256": (
            _digest(result["technicalEvidence"]) if technical_association != "absent"
            else None
        ),
        "sceneSha256": (
            _digest(result["sceneConstraintEvidence"]) if scene_association != "absent"
            else None
        ),
        "technicalAssociation": technical_association,
        "sceneAssociation": scene_association,
        "sceneSourceNote": note,
        "independentlyVerified": False,
    }
    _screen_snapshot(result)
    verify_pmss_evidence_binding(result)
    return result
