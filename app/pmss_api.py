"""Bounded, read-only PMSS snapshot analysis for the React Studio.

The React client uploads a *sanitized* JSON snapshot to this same-origin API.
No PMSS credentials, network connections, submissions or clearing calls exist
in these endpoints. Uploaded JSON is used in memory for the current request.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from threading import BoundedSemaphore
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from powerbid.pmss_bid_rule_safety import (
    summarize_bid_rule_audit,
    validate_new_bid_prices,
    validate_new_curve,
)
from powerbid.network_dispatch import network_from_dict
from powerbid.network_feedback import compare_dc_baseline_to_pmss
from powerbid.network_historical_audit import audit_pmss_historical_grid
from powerbid.network_strategy import evaluate_network_plan, verify_network_inputs
from powerbid.pmss_diagnostics import analyze_historical_network, compare_baseline_to_pmss
from powerbid.pmss_integration import BidSegment, PeriodBid, snapshot_from_pmss
from powerbid.pmss_strategy import optimize_segmented_bid
from powerbid.strategy_lab import DemandStress

router = APIRouter(prefix="/api/pmss")
_NETWORK_LIMITER = BoundedSemaphore(value=1)
MAX_REQUEST_BYTES = 900_000
SENSITIVE_KEYS = {
    "cookie", "cookies", "setcookie", "token", "accesstoken",
    "refreshtoken", "authorization", "password", "passwd",
    "secret", "session", "sessionid", "csrf", "privatekey",
}
ALLOWED_ROOT_KEYS = {
    "unitTree", "unitBids", "marketSystem", "demandForecastMw",
    "forecastSource", "historicalBacktestOnly", "caseDate",
    "results", "loadSourceKind", "loadNodeCount", "dcNetwork",
}


class SnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: dict[str, Any]


class OptimizeInput(SnapshotInput):
    target_unit_id: str = Field(min_length=1, max_length=120)
    candidate_prices: list[float] = Field(min_length=1, max_length=21)
    iterations: int = Field(default=2, ge=1, le=3)
    quantity_step_mw: float | None = Field(default=None, gt=0, le=50_000)


class SegmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start_power: float = Field(ge=0)
    end_power: float = Field(gt=0)
    price: float = Field(ge=0, le=10000)


class NetworkInput(SnapshotInput):
    target_unit_id: str = Field(min_length=1, max_length=120)
    recommended_segments: list[SegmentInput] | None = Field(
        default=None, min_length=1, max_length=5
    )


async def _read_payload(request: Request) -> dict[str, Any]:
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "仅接收 JSON 快照")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_REQUEST_BYTES:
            raise HTTPException(413, "快照过大，请先导出脱敏的 PMSS JSON")
        data.extend(chunk)
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "文件不是有效的 UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(422, "请求体必须是 JSON 对象")
    return parsed


def _screen_snapshot(raw: dict[str, Any]) -> None:
    unknown = set(raw) - ALLOWED_ROOT_KEYS
    if unknown:
        raise ValueError("快照包含意外字段，请使用只读白名单导出器")
    # Fail closed if an upload includes credentials at any depth, not just
    # in root metadata. The operation never writes the original payload.
    nodes = [(raw, 0)]
    visited = 0
    while nodes:
        value, depth = nodes.pop()
        visited += 1
        if visited > 100_000 or depth > 14:
            raise ValueError("快照结构过深或过大")
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError("快照字段必须为字符串")
                lowered = key.lower().replace("_", "").replace("-", "")
                if lowered in SENSITIVE_KEYS or any(
                    part in lowered for part in (
                        "cookie", "token", "password", "secret",
                        "authorization", "session", "csrf", "privatekey",
                    )
                ):
                    raise ValueError("快照包含认证字段；请在服务器端脱敏后再导入")
                nodes.append((child, depth + 1))
        elif isinstance(value, list):
            nodes.extend((child, depth + 1) for child in value)


def _parse_snapshot(raw: dict[str, Any]):
    _screen_snapshot(raw)
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"],
        unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    if len(snapshot.units) > 30:
        raise ValueError("在线演示最多分析 30 台机组")
    return snapshot


def _real_network(raw: dict[str, Any]) -> dict[str, Any] | None:
    results = raw.get("results")
    if results is None:
        return None
    if not isinstance(results, dict):
        raise ValueError("PMSS 历史结果必须是 JSON 对象")
    report = analyze_historical_network(results)
    return {
        "node_count": report.node_count,
        "branch_count": report.branch_count,
        "price_coverage_points": report.price_coverage_points,
        "flow_coverage_points": report.flow_coverage_points,
        "hourly": [asdict(item) for item in report.hourly],
        "most_shadowed": [asdict(item) for item in report.most_shadowed[:12]],
        "description": report.label,
    }


@router.post("/inspect")
async def inspect_snapshot(request: Request) -> dict[str, Any]:
    try:
        params = SnapshotInput.model_validate(await _read_payload(request))
        snapshot = _parse_snapshot(params.snapshot)
        network = _real_network(params.snapshot)
        grid_raw = params.snapshot.get("dcNetwork")
        if grid_raw is not None:
            verified_grid = network_from_dict(grid_raw)
            verify_network_inputs(snapshot, verified_grid, snapshot.units[0].unit_id)
            if len(verified_grid.buses) > 60 or len(verified_grid.lines) > 90:
                raise ValueError("Online DC analysis is limited to 60 buses / 90 lines")
        else:
            verified_grid = None
    except (ValidationError, KeyError, TypeError, ValueError, StopIteration) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {
        "units": [asdict(item) for item in snapshot.units],
        "load_mw": list(snapshot.demand_forecast_mw),
        "forecast_source": snapshot.forecast_source,
        "case_date": str(params.snapshot.get("caseDate", "")),
        "historical_only": bool(params.snapshot.get("historicalBacktestOnly", False)),
        "load_source_kind": str(params.snapshot.get("loadSourceKind", "")),
        "market_type": snapshot.limits.market_type,
        "max_segments": snapshot.limits.max_segments,
        "historical_bid_rule_audit": summarize_bid_rule_audit(snapshot),
        "network": network,
        "dc_grid_available": verified_grid is not None,
        "dc_grid_buses": len(verified_grid.buses) if verified_grid else 0,
        "dc_grid_lines": len(verified_grid.lines) if verified_grid else 0,
        "requires_explicit_pmss_validation": True,
    }


@router.post("/optimize")
async def optimize_snapshot(request: Request) -> dict[str, Any]:
    try:
        params = OptimizeInput.model_validate(await _read_payload(request))
        snapshot = _parse_snapshot(params.snapshot)
        validate_new_bid_prices(snapshot, params.candidate_prices)
        if params.target_unit_id not in snapshot.bids:
            raise ValueError("目标机组不在本次只读快照内")
        result = optimize_segmented_bid(
            snapshot,
            params.target_unit_id,
            candidate_prices=params.candidate_prices,
            iterations=params.iterations,
            quantity_step_mw=params.quantity_step_mw,
        )
        observed = params.snapshot.get("results")
        backtest = None
        if observed is not None:
            if not isinstance(observed, dict):
                raise ValueError("PMSS 结果必须是对象")
            backtest = compare_baseline_to_pmss(
                target_unit_id=params.target_unit_id,
                baseline=result.baseline,
                results=observed,
            )
    except (ValidationError, KeyError, TypeError, ValueError, StopIteration) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {
        "target_unit_id": result.target_unit_id,
        "baseline": {
            "total_profit": result.baseline.total_profit,
            "total_accepted_mwh": result.baseline.total_accepted_mwh,
        },
        "recommended": {
            "segments": [asdict(seg) for seg in result.recommended.segments],
            "total_profit": result.recommended.total_profit,
            "total_accepted_mwh": result.recommended.total_accepted_mwh,
            "hours": [asdict(hour) for hour in result.recommended.hours],
        },
        "evaluated_curves": result.evaluated_curves,
        "baseline_backtest": asdict(backtest) if backtest else None,
        "model": "single-zone uniform-price surrogate",
        "pmss_write_performed": False,
        "pmss_clearing_executed": False,
        "counterfactual_pmss_result_available": False,
    }


def _summary_dc_study(study, grid, target):
    day = study.scenarios[0]
    limits = {line.line_id: line.limit_mw for line in grid.lines}
    hours = []
    for hour in day.hours:
        binding = [
            line for line, flow in hour.branch_flows_mw.items()
            if abs(flow) >= limits[line] - max(0.01, limits[line] * 1e-5)
        ]
        hours.append({
            "period": hour.period,
            "target_mw": hour.dispatched_mw,
            "target_lmp": hour.target_lmp,
            "target_profit": hour.margin,
            "binding_line_count": len(binding),
            "binding_lines": binding,
        })
    return {
        "target_unit_id": target,
        "total_profit": day.total_margin,
        "total_accepted_mwh": day.accepted_mwh,
        "max_line_utilization": max(
            abs(hour.branch_flows_mw[line]) / limit
            for hour in day.hours for line, limit in limits.items()
        ),
        "hours_with_binding_lines": sum(bool(h["binding_lines"]) for h in hours),
        "hours": hours,
        "study_type": study.model_label,
    }


def _run_dc_study(snapshot, network, target, candidate):
    normal = (DemandStress("normal"),)
    baseline = evaluate_network_plan(
        snapshot, network, target,
        "PMSS 原始已申报曲线（DC模型重算）",
        snapshot.bids[target], normal,
    )
    recommended = None
    error = None
    if candidate is not None:
        try:
            plan = (PeriodBid(1, 24, tuple(candidate)),)
            recommended = evaluate_network_plan(
                snapshot, network, target,
                "本地候选报价 DC 对照（非 PMSS）",
                plan, normal,
            )
        except ValueError as exc:
            error = str(exc)
    return baseline, recommended, error


@router.post("/network-evaluate")
async def evaluate_network_snapshot(request: Request) -> dict[str, Any]:
    """Actual-parameter DC approximation, using the existing network engine."""
    try:
        params = NetworkInput.model_validate(await _read_payload(request))
        snapshot = _parse_snapshot(params.snapshot)
        raw = params.snapshot.get("dcNetwork")
        if raw is None:
            raise ValueError("快照未携带经核验的 dcNetwork，请先运行服务器只读映射脚本")
        network = network_from_dict(raw)
        verify_network_inputs(snapshot, network, params.target_unit_id)
        if len(network.buses) > 60 or len(network.lines) > 90:
            raise ValueError("在线 DC 网络分析最多支持60节点、90线路")
        candidate = (
            tuple(
                BidSegment(s.start_power, s.end_power, s.price)
                for s in params.recommended_segments
            )
            if params.recommended_segments is not None else None
        )
        if candidate is not None:
            validate_new_curve(snapshot, params.target_unit_id, candidate)
        if not _NETWORK_LIMITER.acquire(blocking=False):
            raise HTTPException(429, "网络约束模型繁忙，请稍后重试")
        try:
            baseline, proposed, error = await run_in_threadpool(
                _run_dc_study, snapshot, network, params.target_unit_id, candidate
            )
        finally:
            _NETWORK_LIMITER.release()
        historical = None
        historical_grid_audit = None
        historical_unavailable_reason = None
        observed = params.snapshot.get("results")
        if observed is not None:
            try:
                # Before any modeled-versus-history diagnostics, validate
                # original PMSS curve, neutral scenario and exact result IDs.
                historical = asdict(compare_dc_baseline_to_pmss(
                    snapshot, network, baseline, params.target_unit_id, observed
                ))
                historical_grid_audit = asdict(audit_pmss_historical_grid(
                    network,
                    observed,
                    case_date=str(params.snapshot.get("caseDate") or ""),
                    modeled_hours=baseline.scenarios[0].hours,
                    target_unit_id=params.target_unit_id,
                ))
            except (ValueError, KeyError, TypeError) as exc:
                # Do not silently display zero error or a "good" label.
                historical = None
                historical_grid_audit = None
                historical_unavailable_reason = str(exc)
    except (ValidationError, KeyError, TypeError, ValueError, StopIteration) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {
        "baseline": _summary_dc_study(baseline, network, params.target_unit_id),
        "recommended": (
            _summary_dc_study(proposed, network, params.target_unit_id)
            if proposed else None
        ),
        "recommended_error": error,
        "historical_calibration": historical,
        "historical_grid_audit": historical_grid_audit,
        "historical_unavailable_reason": historical_unavailable_reason,
        "topology_source": network.topology_source,
        "network_model": "Existing PowerBid network_dispatch lossless DC-OPF",
        "excluded_constraints": [
            "joint 24h commitment", "ramping", "reserve", "losses",
            "AC voltage/reactive power", "PMSS rule-specific pricing",
        ],
        "pmss_write_performed": False,
        "pmss_clearing_executed": False,
        "pmss_counterfactual_verified": False,
    }
