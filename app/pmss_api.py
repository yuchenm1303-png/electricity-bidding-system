"""Read-only PMSS integration for the React product workspace.

Never accepts credentials or writes to the teacher platform. Uploaded snapshots
are processed in memory; offline estimates are clearly labeled as surrogate.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from powerbid.adapters.teacher_platform import (
    TeacherPlatformAdapter,
    TeacherPlatformError,
)
from powerbid.pmss_diagnostics import (
    analyze_historical_network,
    compare_baseline_to_pmss,
)
from powerbid.pmss_integration import snapshot_from_pmss
from powerbid.pmss_strategy import optimize_segmented_bid
from powerbid.strategy_lab import compare_strategies, stress_grid, tune_policy_grid

router = APIRouter(prefix="/api/pmss", tags=["PMSS read-only research"])
MAX_BYTES = 6 * 1024 * 1024
SENSITIVE_KEYS = {
    "cookie", "cookies", "authorization", "access_token", "refresh_token",
    "token", "password", "secret", "apikey", "api_key", "sessionid",
    "session_id", "set-cookie",
}
NOTICE = (
    "本地单区域统一价代理模型：不含网络潮流、节点电价、机组启停与真实结算；"
    "推荐报价从未提交 PMSS，也不代表老师平台对候选报价的出清结果。"
)


class SnapshotResearch(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    snapshot: dict[str, Any]
    target_unit_id: str = Field(min_length=1, max_length=128)
    mode: str = Field(pattern="^(segments|strategies)$")
    start: float = Field(default=0, ge=0, le=100000)
    stop: float = Field(default=1000, ge=0, le=100000)
    step: float = Field(default=100, gt=0, le=100000)
    iterations: int = Field(default=3, ge=1, le=10)
    quantity_step_mw: float = Field(default=0, ge=0, le=100000)
    markup_max: float = Field(default=100, ge=0, le=10000)
    markup_step: float = Field(default=25, gt=0, le=10000)
    demand_deviation: float = Field(default=0.05, ge=0, le=0.3)
    peer_deviation: float = Field(default=0.05, ge=0, le=0.3)
    risk_aversion: float = Field(default=0.35, ge=0, le=1)
    tail_fraction: float = Field(default=0.25, gt=0, le=1)
    joint_search: bool = False


def _safe_snapshot(raw: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    # Whitelist the exact PMSS data schema, preventing accidental credential upload.
    required = {"unitTree", "unitBids", "marketSystem", "demandForecastMw", "forecastSource"}
    permitted = required | {
        "results", "caseDate", "historicalBacktestOnly", "loadSourceKind",
        "source", "projectName", "caseName",
    }
    if required - raw.keys():
        raise ValueError("快照缺少字段：" + ", ".join(sorted(required - raw.keys())))
    if extra := set(raw) - permitted:
        raise ValueError("快照包含非预期字段：" + ", ".join(sorted(extra)[:6]))
    def scan(item: Any, depth: int = 0) -> None:
        if depth > 20:
            raise ValueError("快照嵌套过深")
        if isinstance(item, dict):
            for key, value in item.items():
                if str(key).lower() in SENSITIVE_KEYS:
                    raise ValueError("快照不得包含账号、密码、Cookie 或 Token")
                scan(value, depth + 1)
        elif isinstance(item, list):
            for value in item:
                scan(value, depth + 1)
    scan(raw)
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"],
        unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    return snapshot, raw


async def _payload(request: Request) -> dict[str, Any]:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(413, "快照过大，请将 JSON 精简至 6 MB 以下")
        chunks.append(chunk)
    try:
        data = json.loads(b"".join(chunks))
        if not isinstance(data, dict):
            raise ValueError("请求数据必须是 JSON 对象")
        return data
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "请求数据不是有效 JSON") from exc


def _inspection(snapshot: Any, raw: dict[str, Any]) -> dict[str, Any]:
    observed = raw.get("results")
    observed_ok = isinstance(observed, dict) and observed.get("periodNum") == 24
    warnings: list[str] = []
    if raw.get("historicalBacktestOnly"):
        warnings.append("此文件仅适用于历史案例回测，不得作为未来负荷预测。")
    if raw.get("loadSourceKind") == "PMSS_DA_SCENE_LOAD_INPUT":
        warnings.append("负荷采用 PMSS 历史日前场景输入，而非未来预测。")
    report: dict[str, Any] | None = None
    diagnostic_error = None
    if observed_ok:
        try:
            network = analyze_historical_network(observed)
            report = asdict(network)
        except (KeyError, TypeError, ValueError) as exc:
            diagnostic_error = str(exc)
    return {
        "units": [asdict(u) for u in snapshot.units],
        "periods": snapshot.period_num,
        "demand_forecast_mw": list(snapshot.demand_forecast_mw),
        "forecast_source": snapshot.forecast_source,
        "limits": asdict(snapshot.limits),
        "historical_only": bool(raw.get("historicalBacktestOnly")),
        "has_observed": observed_ok,
        "network": report,
        "network_error": diagnostic_error,
        "warnings": warnings,
        "notice": NOTICE,
    }


@router.post("/snapshot/inspect")
async def inspect(request: Request) -> dict[str, Any]:
    data = await _payload(request)
    try:
        raw = data["snapshot"]
        if not isinstance(raw, dict):
            raise ValueError("snapshot 必须是对象")
        snapshot, raw = _safe_snapshot(raw)
        return _inspection(snapshot, raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


def _prices(start: float, stop: float, step: float, limit: int) -> list[float]:
    if start > stop or (stop - start) / step > limit - 1:
        raise ValueError(f"搜索范围过大，最多支持 {limit} 个报价档位")
    count = int((stop - start) / step)
    values = [round(start + i * step, 8) for i in range(count + 1)]
    if values[-1] < stop - 1e-6:
        values.append(stop)
    return values


@router.post("/snapshot/optimize")
async def offline_optimize(request: Request) -> dict[str, Any]:
    data = await _payload(request)
    try:
        options = SnapshotResearch.model_validate(data)
        snapshot, raw = _safe_snapshot(options.snapshot)
        if options.target_unit_id not in snapshot.bids:
            raise ValueError("目标机组不在 PMSS 快照中")
        if options.mode == "segments":
            if not snapshot.limits.same_curve:
                raise ValueError("该 PMSS 规则允许逐小时报价，请使用策略研究室，而非共用曲线优化器")
            result = optimize_segmented_bid(
                snapshot, options.target_unit_id,
                candidate_prices=_prices(options.start, options.stop, options.step, 201),
                quantity_step_mw=options.quantity_step_mw or None,
                iterations=options.iterations,
            )
            backtest = None
            backtest_error = None
            observed = raw.get("results")
            if isinstance(observed, dict) and observed.get("periodNum") == 24:
                try:
                    backtest = asdict(compare_baseline_to_pmss(
                        target_unit_id=options.target_unit_id,
                        baseline=result.baseline, results=observed,
                    ))
                except (ValueError, KeyError, TypeError) as exc:
                    backtest_error = str(exc)
            return {
                "mode": "segments",
                "result": asdict(result),
                "backtest": backtest,
                "backtest_error": backtest_error,
                "notice": NOTICE,
                "historical_only": bool(raw.get("historicalBacktestOnly")),
            }
        markups = _prices(0, options.markup_max, options.markup_step, 20)
        cases = stress_grid(
            demand_deviation=options.demand_deviation,
            peer_price_deviation=options.peer_deviation,
        )
        if options.joint_search:
            comparison = tune_policy_grid(
                snapshot, options.target_unit_id,
                markups=markups,
                slopes=(0.0, 10.0, 25.0),
                scarcity_sensitivities=(0.0, 50.0, 100.0),
                scenarios=cases,
                risk_aversion=options.risk_aversion,
                tail_fraction=options.tail_fraction,
                max_evaluations=180,
            )
        else:
            comparison = compare_strategies(
                snapshot, options.target_unit_id,
                markups=markups, scenarios=cases,
                risk_aversion=options.risk_aversion,
                tail_fraction=options.tail_fraction,
            )
        return {
            "mode": "strategies",
            "result": asdict(comparison),
            "notice": NOTICE,
            "historical_only": bool(raw.get("historicalBacktestOnly")),
        }
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


def _client() -> TeacherPlatformAdapter:
    base = os.getenv("POWERBID_PLATFORM_BASE_URL", "").strip()
    if not base:
        raise HTTPException(503, "尚未配置老师平台只读桥接，仍可上传快照进行离线研究")
    return TeacherPlatformAdapter(base_url=base, timeout=12)


def _safe_live_error(exc: Exception) -> HTTPException:
    # Never leak internal proxy addresses or cookies through HTTP error text.
    return HTTPException(502, f"老师 PMSS 只读接口暂时不可用（{type(exc).__name__}）")


def _context(client: TeacherPlatformAdapter) -> Any:
    context = client.get_context()
    if not context.cases:
        raise ValueError("老师平台当前工程没有可用案例")
    if not context.units:
        raise ValueError("老师平台当前工程没有机组")
    return context


@router.get("/live/status")
def live_status() -> dict[str, Any]:
    configured = bool(os.getenv("POWERBID_PLATFORM_BASE_URL", "").strip())
    return {"configured": configured, "read_only": True, "write_enabled": False}


@router.get("/live/context")
def live_context() -> dict[str, Any]:
    try:
        context = _context(_client())
        return {
            "project": {
                "projectId": context.project.get("projectId"),
                "projectName": context.project.get("projectName"),
                "netName": context.project.get("netName"),
            },
            "market_name": context.market_system.get("marketSystemName"),
            "cases": [
                {"caseId": str(c.get("caseId") or ""),
                 "caseDate": c.get("caseDate") or c.get("caseName") or "",
                 "tmSceneDateKey": c.get("tmSceneDateKey")}
                for c in context.cases
            ],
            "units": [
                {"unitId": str(u.get("key") or u.get("unitId") or ""),
                 "name": u.get("title") or u.get("name"),
                 "capacity": u.get("pdAdjustMax") or u.get("mvarate"),
                 "runningCost": u.get("runningCost")}
                for u in context.units
            ],
            "read_only": True,
        }
    except (TeacherPlatformError, ValueError, KeyError, RuntimeError) as exc:
        raise _safe_live_error(exc) from exc


@router.get("/live/detail")
def live_detail(case_id: str, unit_id: str) -> dict[str, Any]:
    if not 1 <= len(case_id) <= 128 or not 1 <= len(unit_id) <= 128:
        raise HTTPException(422, "案例或机组编号无效")
    try:
        client = _client()
        context = _context(client)
        case = next((c for c in context.cases if str(c.get("caseId")) == case_id), None)
        unit = next(
            (u for u in context.units if str(u.get("key") or u.get("unitId")) == unit_id),
            None,
        )
        if case is None or unit is None:
            raise HTTPException(404, "案例或机组不在当前工程中")
        scope_id = context.scope_id(case=case, market_type_atom="DA")
        bid = client.get_unit_bid(scope_id=scope_id, unit_id=unit_id)
        clearing = client.get_clearing_result(case_id=case_id, market_type_atom="DA")
        unit_result = client.get_unit_results(case_id=case_id, da_ids=[unit_id], rt_ids=[])
        overview = client.get_result_overview(case_id=case_id, market_type_atom="DA")
        rows = [
            row for row in unit_result.get("datas", [])
            if row.get("marketTypeAtom") == "DA"
        ]
        selected = rows[0] if rows else {}
        return {
            "case_id": case_id,
            "unit_id": unit_id,
            "unit": {
                "name": unit.get("title"),
                "capacity": unit.get("pdAdjustMax") or unit.get("mvarate"),
                "running_cost": unit.get("runningCost"),
            },
            "segments": [
                {"start_period": p.get("startPeriod"), "end_period": p.get("endPeriod"),
                 "segments": [
                     {"start_power": s.get("startPower"),
                      "end_power": s.get("endPower"), "price": s.get("price")}
                     for s in p.get("segmentDatas", [])
                 ]}
                for p in (bid.get("datas") or [])
            ],
            "accepted_mw": (selected.get("power") or {}).get("datas") or [],
            "clearing_prices": (selected.get("price") or {}).get("datas") or [],
            "income": (selected.get("income") or {}).get("datas") or [],
            "overview": {
                key: overview.get(key) for key in (
                    "systemHighestSysLoad", "systemUnitAvgLmp",
                    "marketUnitIncome", "blockSurplus",
                )
            },
            "converged": (clearing.get("optResult") or {}).get("isConverge") == 1,
            "read_only": True,
        }
    except HTTPException:
        raise
    except (TeacherPlatformError, ValueError, KeyError, RuntimeError, TypeError) as exc:
        raise _safe_live_error(exc) from exc
