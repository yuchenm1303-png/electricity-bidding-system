"""Admin-confirmed handoff to the ORIGINAL school PMSS clearing engine.

No browser credentials. No automatic school writes. Each irreversible POST has a
persistent single-use state transition, no retry, and an explicit human click.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.account_auth import require_user
from app.pmss_readonly_api import _catalog
from powerbid.adapters.teacher_platform import (
    TeacherPlatformAdapter,
    TeacherPlatformAuthenticationExpired,
    TeacherPlatformError,
)
from powerbid.pmss_integration import MarketLimits
from powerbid.pmss_result_loader import read_market_results

router = APIRouter(prefix="/api/pmss/live", tags=["pmss-original-clearing"])
_DB = "/data/pmss-live-intents.sqlite3"
_MAX_AGE = 15 * 60


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start_power: float = Field(ge=0, le=20000)
    end_power: float = Field(gt=0, le=20000)
    price: float = Field(ge=0, le=10000)


class PrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1, max_length=100)
    case_date: date
    target_unit_id: str = Field(min_length=1, max_length=100)
    segments: list[Segment] = Field(min_length=1, max_length=5)


class ConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_token: str = Field(min_length=30, max_length=150)
    confirmation: str = Field(min_length=1, max_length=180)


def _json_file(path: str) -> dict[str, Any]:
    file = Path(path)
    if not path or file.is_symlink() or not file.is_file():
        raise ValueError("Private PMSS configuration is missing")
    stat = file.stat()
    if stat.st_mode & 0o077 or stat.st_size > 64_000:
        raise ValueError("Private PMSS configuration must be owner-only JSON")
    result = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Private PMSS configuration must be a JSON object")
    return result


def _gateway_available() -> bool:
    return (os.getenv("PMSS_LIVE_GATEWAY_ENABLED") == "1"
            and os.getenv("PMSS_LIVE_GATEWAY_URL") == "http://172.17.0.1:18762"
            and bool(os.getenv("PMSS_LIVE_WRITE_TOKEN_FILE"))
            and bool(os.getenv("PMSS_LIVE_PROJECT_MAP_FILE")))


def _adapter() -> TeacherPlatformAdapter:
    if _gateway_available():
        # The school cookies stay IN MEMORY inside the existing server VPN
        # bridge. PowerBid knows only a private write-gate capability token.
        token_path = os.getenv("PMSS_LIVE_WRITE_TOKEN_FILE", "")
        path = Path(token_path)
        if not token_path or path.is_symlink() or not path.is_file():
            raise ValueError("Private school write authorization is missing")
        info = path.stat()
        if info.st_mode & 0o077 or not 40 <= info.st_size <= 256:
            raise ValueError("Private school write authorization is invalid")
        token = path.read_text("ascii").strip()
        if len(token) < 40:
            raise ValueError("Private school write authorization is invalid")
        adapter = TeacherPlatformAdapter(
            base_url="http://172.17.0.1:18762",
            write_gate_token=token, timeout=45,
        )
        if not adapter.write_gateway_ready():
            raise ValueError("Restricted original PMSS write gateway is not ready")
        return adapter
    base = os.getenv("PMSS_BASE_URL", "")
    cookie_path = os.getenv("PMSS_COOKIE_FILE", "")
    if not base or not cookie_path:
        raise ValueError("School PMSS server-side connection is not configured")
    cookies = _json_file(cookie_path)
    if not cookies or any(type(k) is not str or not k or
                          type(v) is not str or not v for k, v in cookies.items()):
        raise ValueError("Private PMSS cookies are malformed")
    return TeacherPlatformAdapter(
        base_url=base, proxy_url=os.getenv("PMSS_PROXY_URL") or None,
        cookies=cookies, timeout=12,
    )


def _remote_project_id(local_id: str) -> str:
    """The browser can select ONLY a catalog project mapped by the operator."""
    projects = _json_file(os.getenv("PMSS_LIVE_PROJECT_MAP_FILE", ""))
    if any(type(k) is not str or type(v) is not str or
           not k or not v or len(k) > 100 or len(v) > 120
           for k, v in projects.items()):
        raise ValueError("Invalid private school project mapping")
    remote = projects.get(local_id)
    if not remote:
        raise ValueError("No school project mapping configured for this case")
    return remote


def _database() -> sqlite3.Connection:
    db_path = Path(os.getenv("PMSS_LIVE_INTENTS_DB", _DB))
    if not db_path.parent.is_dir() or db_path.is_symlink():
        raise RuntimeError("Private local attempt directory unavailable")
    if not db_path.exists():
        fd = os.open(db_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
    con = sqlite3.connect(db_path, timeout=8)
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS intents (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
          created INTEGER NOT NULL, state TEXT NOT NULL,
          project_id TEXT NOT NULL, case_date TEXT NOT NULL,
          unit_id TEXT NOT NULL, case_id TEXT NOT NULL,
          payload TEXT NOT NULL
        )
    """)
    con.execute("CREATE TABLE IF NOT EXISTS result_baselines "
                "(token_hash TEXT PRIMARY KEY, digest TEXT NOT NULL)")
    con.commit()
    return con


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _store(user_id: int, local_id: str, case_date: str, unit_id: str,
           case_id: str, payload: dict[str, Any]) -> str:
    token = secrets.token_urlsafe(36)
    with _database() as db:
        db.execute("BEGIN IMMEDIATE")
        # A new token must NOT bypass an uncertain prior upstream write.
        previous = db.execute(
            "SELECT 1 FROM intents WHERE project_id=? AND case_date=? AND unit_id=? "
            "AND state IN ('SAVING', 'SAVE_ACKNOWLEDGED', 'UNKNOWN_SAVE', "
            "'VERIFIED_SAVED', 'CLEARING', 'UNKNOWN_CLEARING', 'CLEARING_REQUESTED') "
            "LIMIT 1",
            (local_id, case_date, unit_id),
        ).fetchone()
        if previous:
            raise HTTPException(
                409, "此学校案例与机组已有提交或状态不确定记录，禁止重复创建出清操作"
            )
        db.execute(
            "INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)",
            (_token_hash(token), user_id, int(time.time()), "PREPARED",
             local_id, case_date, unit_id, case_id,
             json.dumps(payload, ensure_ascii=False, allow_nan=False)),
        )
    return token


def _intent(token: str, user_id: int) -> sqlite3.Row:
    if len(token) < 30 or len(token) > 150:
        raise HTTPException(404, "操作记录不存在")
    with _database() as db:
        row = db.execute(
            "SELECT * FROM intents WHERE token_hash=? AND user_id=?",
            (_token_hash(token), user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "操作记录不存在")
    return row


def _transition(token: str, user_id: int, expected: tuple[str, ...], to: str) -> sqlite3.Row:
    with _database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM intents WHERE token_hash=? AND user_id=?",
            (_token_hash(token), user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "操作记录不存在")
        if row["state"] not in expected:
            raise HTTPException(409, "该操作已执行或状态未确认，不会再次发送学校请求")
        if int(time.time()) - row["created"] > _MAX_AGE and to in ("SAVING", "CLEARING"):
            raise HTTPException(409, "报价确认已过期，请重新生成预览")
        db.execute(
            "UPDATE intents SET state=? WHERE token_hash=? AND user_id=?",
            (to, _token_hash(token), user_id),
        )
    return row


def _mark(token: str, user_id: int, state: str) -> None:
    with _database() as db:
        db.execute(
            "UPDATE intents SET state=? WHERE token_hash=? AND user_id=?",
            (state, _token_hash(token), user_id),
        )


def _school_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TeacherPlatformAuthenticationExpired):
        return HTTPException(409, "学校 PMSS 登录已过期，需要在官方页面重新认证")
    return HTTPException(503, "学校 PMSS 服务暂不可用，请检查学校会话和网络")


def _case_date(case: dict[str, Any]) -> str | None:
    for field in ("caseDate", "tmSceneDate", "simulateDate", "date"):
        value = case.get(field)
        if isinstance(value, str) and len(value) >= 10:
            try:
                return date.fromisoformat(value[:10]).isoformat()
            except ValueError:
                pass
    return None


def _remote_case(adapter: TeacherPlatformAdapter, remote_project: str,
                 selected_date: str, unit_id: str):
    ctx = adapter.get_context(remote_project)
    matches = [c for c in ctx.cases if isinstance(c, dict)
               and _case_date(c) == selected_date]
    if len(matches) != 1:
        raise ValueError("学校场景日期无法唯一对应，不能提交")
    case = matches[0]
    unit_matches = [u for u in ctx.units
                    if str(u.get("key", u.get("unitId", ""))) == unit_id]
    if len(unit_matches) != 1:
        raise ValueError("学校机组身份与本地报价不一致，不能提交")
    scope = ctx.scope_id(case=case, market_type_atom="DA")
    if not ctx.day_ahead:
        raise ValueError("学校场景缺少日前市场规则")
    return ctx, case, unit_matches[0], scope


def _readback_matches(original: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Compare only the exact submitted DA 24h price/quantity blocks."""
    datas = original.get("datas")
    if not isinstance(datas, list) or len(datas) != 1:
        return False
    period = datas[0]
    if not isinstance(period, dict) or int(period.get("startPeriod", -1)) != 1 or (
        int(period.get("endPeriod", -1)) != 24
    ):
        return False
    blocks = period.get("segmentDatas")
    wanted = payload["datas"][0]["segmentDatas"]
    if not isinstance(blocks, list) or len(blocks) != len(wanted):
        return False
    try:
        return all(all(abs(float(b[field]) - float(w[field])) <= 1e-6
                       for field in ("startPower", "endPower", "price"))
                   for b, w in zip(blocks, wanted, strict=True))
    except (ValueError, TypeError, KeyError):
        return False


def _readonly_bridge_adapter() -> TeacherPlatformAdapter:
    """Read-only school bridge, never used for save or clearing."""
    endpoint = os.getenv("PMSS_READONLY_BRIDGE_URL", "")
    if endpoint != "http://172.17.0.1:18762":
        raise ValueError("Private read-only school bridge unavailable")
    return TeacherPlatformAdapter(base_url=endpoint, timeout=10)


def _readonly_school_status() -> str:
    try:
        adapter = _readonly_bridge_adapter()
        adapter.list_projects(page_no=1, page_size=1)
    except TeacherPlatformAuthenticationExpired:
        return "login_required"
    except (TeacherPlatformError, ValueError, OSError):
        return "unavailable"
    return "authorized"


@router.get("/school-preflight")
def school_preflight(request: Request, project_id: str,
                     case_date: date, target_unit_id: str):
    """School-only queries; no school write or local intent creation."""
    require_user(request, admin=True)
    if not (1 <= len(project_id) <= 100 and 1 <= len(target_unit_id) <= 100):
        raise HTTPException(422, "学校工程或机组标识不合法")
    try:
        root, projects = _catalog()
        item = next((x for x in projects if x["project_id"] == project_id), None)
        day = case_date.isoformat()
        if not root.is_dir() or not item or not any(
            x["case_date"] == day for x in item["cases"]
        ):
            raise ValueError("Case not found in authenticated catalog")
        adapter = _readonly_bridge_adapter()
        remote_projects = adapter.list_projects(page_no=1, page_size=50)
        candidates = [
            x for x in remote_projects
            if isinstance(x, dict) and x.get("projectName") == item["name"]
        ]
        if len(candidates) != 1:
            raise ValueError("School project does not uniquely match")
        remote_id = str(candidates[0]["projectId"])
        ctx, case, unit, scope = _remote_case(
            adapter, remote_id, day, target_unit_id
        )
        rules = MarketLimits.from_pmss(ctx.market_system)
        if not rules.same_curve or rules.price_floor is None or rules.price_ceiling is None:
            raise ValueError("School day-ahead rules do not match local mode")
        existing = adapter.get_unit_bid(
            scope_id=scope, unit_id=target_unit_id
        )
        blocks = existing.get("datas") if isinstance(existing, dict) else None
        count = 0
        if isinstance(blocks, list):
            count = sum(len(x.get("segmentDatas", []))
                        for x in blocks if isinstance(x, dict))
        cost_keys = (
            "minTechPowerCost", "startCostHot", "startCostWarm", "startCostCold"
        )
        cost_ready = isinstance(existing, dict) and all(
            key in existing for key in cost_keys
        )
        return {
            "source": "TEACHER_PMSS_BRIDGE_READ_ONLY",
            "school_authenticated": True,
            "read_only": True,
            "teacher_write_performed": False,
            "teacher_clearing_executed": False,
            "project_id": project_id,
            "project_name": item["name"],
            "case_date": day,
            "target_unit_id": target_unit_id,
            "target_unit_name": str(unit.get("title", "")),
            "school_unit_capacity_mva": unit.get("mvarate"),
            "school_case_mapped": bool(case.get("caseId")),
            "price_limits": [rules.price_floor, rules.price_ceiling],
            "max_segments": rules.max_segments,
            "same_curve_all_day": rules.same_curve,
            "existing_school_bid_blocks": count,
            "original_cost_fields_present": cost_ready,
            "original_write_configured": bool(
                os.getenv("PMSS_BASE_URL")
                and os.getenv("PMSS_COOKIE_FILE")
                and os.getenv("PMSS_LIVE_PROJECT_MAP_FILE")
            ),
        }
    except TeacherPlatformAuthenticationExpired:
        raise HTTPException(409, "学校登录已过期，请由管理员在 PowerBid 内重新认证") from None
    except (TeacherPlatformError, ValueError, OSError, KeyError, TypeError):
        raise HTTPException(422, "学校只读数据与选定工程、日期或机组未能核对一致") from None


@router.get("/status")
def live_status(request: Request):
    require_user(request, admin=True)
    configured = (_gateway_available() or
                  bool(os.getenv("PMSS_BASE_URL") and
                       os.getenv("PMSS_COOKIE_FILE") and
                       os.getenv("PMSS_LIVE_PROJECT_MAP_FILE")))
    if not configured:
        return {"configured": False, "school_auth": "not_configured",
                "live_write_enabled": False,
                "read_only_school_auth": _readonly_school_status()}
    try:
        adapter = _adapter()
        adapter.list_projects(page_no=1, page_size=1)
    except TeacherPlatformAuthenticationExpired:
        state = "login_required"
    except (TeacherPlatformError, ValueError, OSError):
        state = "unavailable"
    else:
        state = "authorized"
    return {"configured": True, "school_auth": state,
            "live_write_enabled": state == "authorized",
            "read_only_school_auth": _readonly_school_status()}


@router.post("/prepare")
def prepare(request: Request, body: PrepareInput):
    user = require_user(request, admin=True)
    selected_date = body.case_date.isoformat()
    try:
        root, projects = _catalog()
        project = next((p for p in projects if p["project_id"] == body.project_id), None)
        if not project or not any(c["case_date"] == selected_date for c in project["cases"]):
            raise ValueError("所选工程日期不在本地已授权案例内")
        if not root.is_dir():
            raise ValueError("历史案例目录缺失")
        remote_project = _remote_project_id(body.project_id)
        adapter = _adapter()
        ctx, case, unit, scope = _remote_case(
            adapter, remote_project, selected_date, body.target_unit_id,
        )
        rule = MarketLimits.from_pmss(ctx.market_system)
        if not rule.same_curve:
            raise ValueError("当前学校市场规则不是24小时共用五段曲线，暂不支持自动提交")
        if rule.price_floor is None or rule.price_ceiling is None:
            raise ValueError("当前学校报价价格上下限缺失")
        segments = [{"startPower": s.start_power, "endPower": s.end_power,
                     "price": s.price} for s in body.segments]
        max_power = float(unit.get("mvarate", unit.get("pdAdjustMax", 0)))
        if max_power <= 0:
            raise ValueError("学校机组容量无效")
        adapter.validate_segments(
            segments, max_segments=rule.max_segments,
            price_min=rule.price_floor, price_max=rule.price_ceiling,
            max_power=max_power,
        )
        old = adapter.get_unit_bid(scope_id=scope, unit_id=body.target_unit_id)
        cost_names = ("minTechPowerCost", "startCostHot", "startCostWarm", "startCostCold")
        if not isinstance(old, dict) or any(name not in old for name in cost_names):
            raise ValueError("学校原始报价成本字段未齐全，禁止用零覆盖")
        costs = [float(old[name]) for name in cost_names]
        if any(not (-1e9 < x < 1e9) for x in costs):
            raise ValueError("学校原始成本字段无效")
        payload = adapter.build_unit_bid_payload(
            scope_id=scope, unit_id=body.target_unit_id, segments=segments,
            min_tech_power_cost=costs[0], start_cost_hot=costs[1],
            start_cost_warm=costs[2], start_cost_cold=costs[3],
        )
        case_id = str(case.get("caseId", ""))
        if not case_id:
            raise ValueError("学校案例标识缺失")
    except (TeacherPlatformError, ValueError, OSError, KeyError, TypeError) as exc:
        if isinstance(exc, ValueError) and not isinstance(exc, TeacherPlatformError):
            raise HTTPException(422, "学校工程、日期或报价规则未核实，已拒绝预览") from exc
        raise _school_error(exc) from None
    token = _store(user["id"], body.project_id, selected_date,
                   body.target_unit_id, case_id, payload)
    return {"intent_token": token, "project_id": body.project_id,
            "case_date": selected_date, "target_unit_id": body.target_unit_id,
            "state": "PREPARED", "segments": payload["datas"][0]["segmentDatas"],
            "price_limits": [rule.price_floor, rule.price_ceiling],
            "expires_in_seconds": _MAX_AGE,
            "teacher_write_performed": False,
            "teacher_clearing_executed": False}


@router.post("/submit")
def submit(request: Request, body: ConfirmInput):
    user = require_user(request, admin=True)
    row = _intent(body.intent_token, user["id"])
    if body.confirmation != f"提交报价 {row['unit_id']} {row['case_date']}":
        raise HTTPException(422, "请确认真实学校机组和日期后再提交")
    row = _transition(body.intent_token, user["id"], ("PREPARED",), "SAVING")
    try:
        _adapter().save_unit_bid(json.loads(row["payload"]), commit=True)
    except (TeacherPlatformError, ValueError, OSError) as exc:
        # Unknown after a write attempt: never replay an ambiguous POST.
        _mark(body.intent_token, user["id"], "UNKNOWN_SAVE")
        raise _school_error(exc) from None
    _mark(body.intent_token, user["id"], "SAVE_ACKNOWLEDGED")
    return {"state": "SAVE_ACKNOWLEDGED", "readback_verified": False,
            "next_step": "只读核对学校保存记录后才能执行出清"}


@router.post("/verify-saved")
def verify_saved(request: Request, body: ConfirmInput):
    user = require_user(request, admin=True)
    row = _intent(body.intent_token, user["id"])
    if row["state"] not in ("SAVE_ACKNOWLEDGED", "UNKNOWN_SAVE"):
        raise HTTPException(409, "尚未完成报价保存，不能核对")
    try:
        payload = json.loads(row["payload"])
        found = _adapter().get_unit_bid(
            scope_id=payload["scopeId"], unit_id=row["unit_id"],
        )
        verified = _readback_matches(found, payload)
    except (TeacherPlatformError, ValueError, OSError) as exc:
        raise _school_error(exc) from None
    if not verified:
        return {"state": row["state"], "readback_verified": False,
                "message": "老师平台返回的五段报价与计划不一致，已停止出清"}
    _mark(body.intent_token, user["id"], "VERIFIED_SAVED")
    return {"state": "VERIFIED_SAVED", "readback_verified": True}


def _result_digest(status, overview, market):
    # Iteration counts/timing alone can change while old market results remain.
    status = status.get("optResult", status)
    costs = {k: status.get(k) for k in ("totalCost", "totalRunCost", "totalStartCost")}
    raw = json.dumps([costs, overview, market], sort_keys=True,
                     separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


@router.post("/execute")
def execute(request: Request, body: ConfirmInput):
    user = require_user(request, admin=True)
    row = _intent(body.intent_token, user["id"])
    if body.confirmation != f"执行出清 {row['unit_id']} {row['case_date']}":
        raise HTTPException(422, "必须再次确认本次学校出清操作")
    if row["state"] != "VERIFIED_SAVED":
        raise HTTPException(409, "报价尚未核验或出清已经尝试，禁止重复执行")
    try:
        adapter = _adapter()
        baseline_status = adapter.get_clearing_result(case_id=row["case_id"], market_type_atom="DA")
        baseline_overview = adapter.get_result_overview(case_id=row["case_id"], market_type_atom="DA")
        baseline_market = read_market_results(adapter, case_id=row["case_id"])
        digest = _result_digest(baseline_status, baseline_overview, baseline_market)
    except (TeacherPlatformError, ValueError, OSError) as exc:
        raise _school_error(exc) from None
    with _database() as db:
        db.execute("INSERT OR REPLACE INTO result_baselines VALUES (?, ?)",
                   (_token_hash(body.intent_token), digest))
    row = _transition(body.intent_token, user["id"], ("VERIFIED_SAVED",), "CLEARING")
    try:
        adapter.run_clearing(case_id=row["case_id"],
                                comment="PowerBid user-confirmed classroom test",
                                commit=True)
    except (TeacherPlatformError, ValueError, OSError) as exc:
        _mark(body.intent_token, user["id"], "UNKNOWN_CLEARING")
        raise _school_error(exc) from None
    _mark(body.intent_token, user["id"], "CLEARING_REQUESTED")
    return {"state": "CLEARING_REQUESTED", "clearing_finished": False,
            "next_step": "查询老师 PMSS 原始出清结果；不得重复执行"}


@router.get("/result")
def result(request: Request, intent_token: str):
    user = require_user(request, admin=True)
    row = _intent(intent_token, user["id"])
    if row["state"] not in ("CLEARING_REQUESTED", "UNKNOWN_CLEARING"):
        raise HTTPException(409, "没有可查询的学校出清尝试")
    try:
        adapter = _adapter()
        status = adapter.get_clearing_result(
            case_id=row["case_id"], market_type_atom="DA",
        )
        overview = adapter.get_result_overview(
            case_id=row["case_id"], market_type_atom="DA",
        )
    except (TeacherPlatformError, ValueError, OSError) as exc:
        raise _school_error(exc) from None
    try:
        market = read_market_results(adapter, case_id=row["case_id"])
        target = next(x for x in market["unitResults"] if x["unit_id"] == row["unit_id"])
        complete = all(v is not None for key in ("accepted_mw", "clearing_prices", "income")
                       for v in target[key])
        with _database() as db:
            baseline = db.execute("SELECT digest FROM result_baselines WHERE token_hash=?",
                                  (_token_hash(intent_token),)).fetchone()
        changed = bool(baseline and baseline["digest"] != _result_digest(status, overview, market))
    except (TeacherPlatformError, ValueError, OSError, StopIteration) as exc:
        raise _school_error(exc) from None
    # Historical results alone never prove completion of this new attempt.
    status = status.get("optResult", status)
    finished = bool(complete and changed and status.get("isConverge") in (True, 1))
    # Only a small documented overview; no raw teacher responses are exposed.
    allowed = ("isConverge", "isRelax", "relaxNum", "iters", "totalCost",
               "totalRunCost", "totalStartCost")
    status_out = {key: status.get(key) for key in allowed if key in status}
    overview_out = {key: overview.get(key) for key in allowed if key in overview}
    return {"state": row["state"], "case_date": row["case_date"],
            "target_unit_id": row["unit_id"], "school_clearing_status": status_out,
            "school_result_overview": overview_out,
            "school_target_unit_result": target,
            "school_nodal_prices": market["nodalPrices"],
            "accepted_mwh": sum(target["accepted_mw"]) if complete else None,
            "school_income": sum(target["income"]) if complete else None,
            "result_changed_since_execution_baseline": changed,
            "clearing_finished": finished,
            "source": "TEACHER_PMSS_DIRECT_READ", "teacher_response_signed": False,
            "candidate_causality_independently_verified": False}
