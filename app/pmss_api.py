"""Bounded, read-only PMSS snapshot analysis for the React Studio.

The React client uploads a *sanitized* JSON snapshot to this same-origin API.
No PMSS credentials, network connections, submissions or clearing calls exist
in these endpoints. Uploaded JSON is used in memory for the current request.
"""
from __future__ import annotations

import json
from threading import BoundedSemaphore
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from powerbid.pmss_dc_network import evaluate_dc_bid, parse_grid
from powerbid.pmss_diagnostics import analyze_historical_network, compare_baseline_to_pmss
from powerbid.pmss_integration import BidSegment
from powerbid.pmss_integration import snapshot_from_pmss
from powerbid.pmss_strategy import optimize_segmented_bid

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
    "results", "loadSourceKind", "loadNodeCount", "grid",
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
        grid_raw = params.snapshot.get("grid")
        if grid_raw is not None:
            verified_grid = parse_grid(grid_raw, snapshot=snapshot)
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
        if any(price < 0 or price > 10_000 for price in params.candidate_prices):
            raise ValueError("候选价格必须处于 0–10000；正式提交仍须核对课程规则")
        snapshot = _parse_snapshot(params.snapshot)
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


def _summary_dc_study(study):
    return {
        "target_unit_id": study.target_unit_id,
        "total_profit": study.total_profit,
        "total_accepted_mwh": study.total_accepted_mwh,
        "max_line_utilization": study.max_line_utilization,
        "hours_with_binding_lines": study.hours_with_binding_lines,
        "hours": [
            {
                "period": h.period,
                "target_mw": h.target_mw,
                "target_lmp": h.target_lmp,
                "target_profit": h.target_profit,
                "binding_line_count": len(h.congested_lines),
                "binding_lines": list(h.congested_lines),
            }
            for h in study.hours
        ],
        "study_type": study.study_type,
    }


def _run_dc_study(snapshot, grid, target, candidate):
    baseline = evaluate_dc_bid(grid, snapshot, target)
    recommended = None
    error = None
    if candidate is not None:
        try:
            recommended = evaluate_dc_bid(
                grid, snapshot, target, target_segments=candidate
            )
        except ValueError as exc:
            error = str(exc)
    return baseline, recommended, error


@router.post("/network-evaluate")
async def evaluate_network_snapshot(request: Request) -> dict[str, Any]:
    """Bounded 24h DC OPF comparison, with no PMSS read/write/clearing calls."""
    try:
        params = NetworkInput.model_validate(await _read_payload(request))
        snapshot = _parse_snapshot(params.snapshot)
        raw_grid = params.snapshot.get("grid")
        if raw_grid is None:
            raise ValueError("此快照没有核验的节点拓扑与线路容量，请先使用服务器只读合并工具")
        grid = parse_grid(raw_grid, snapshot=snapshot)
        if len(grid.buses) > 60 or len(grid.lines) > 90:
            raise ValueError("在线网络优化最多支持60节点、90支路")
        if params.target_unit_id not in grid.unit_buses:
            raise ValueError("目标机组缺少真实接入节点")
        candidate = (
            tuple(
                BidSegment(s.start_power, s.end_power, s.price)
                for s in params.recommended_segments
            )
            if params.recommended_segments is not None else None
        )
        if not _NETWORK_LIMITER.acquire(blocking=False):
            raise HTTPException(429, "网络约束计算正在运行，请稍后重试")
        try:
            # HiGHS is CPU-bound: do not block the web event loop.
            baseline, proposed, error = await run_in_threadpool(
                _run_dc_study, snapshot, grid, params.target_unit_id, candidate
            )
        finally:
            _NETWORK_LIMITER.release()
    except (ValidationError, KeyError, TypeError, ValueError, StopIteration) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {
        "baseline": _summary_dc_study(baseline),
        "recommended": _summary_dc_study(proposed) if proposed else None,
        "recommended_error": error,
        "topology_source": grid.provenance,
        "network_model": "24 independent hourly DC-OPF LPs with actual line x/thermal limits",
        "excluded_constraints": [
            "unit commitment", "intertemporal ramp", "minimum up/down",
            "reserve", "losses", "AC voltage/reactive power", "PMSS rule-specific pricing",
        ],
        "pmss_write_performed": False,
        "pmss_clearing_executed": False,
        "pmss_counterfactual_verified": False,
    }
