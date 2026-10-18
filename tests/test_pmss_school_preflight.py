"""School preflight must be truly read only, isolated from live bid submission."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import pmss_live_api as live


def test_status_exposes_independent_readonly_school_auth(monkeypatch):
    monkeypatch.delenv("PMSS_BASE_URL", raising=False)
    monkeypatch.delenv("PMSS_COOKIE_FILE", raising=False)
    monkeypatch.delenv("PMSS_LIVE_PROJECT_MAP_FILE", raising=False)
    monkeypatch.setattr(live, "require_user", lambda req, admin=False: {"role":"admin"})
    monkeypatch.setattr(live, "_readonly_school_status", lambda: "authorized")
    response=live.live_status(None)
    assert response == {
        "configured": False,
        "school_auth": "not_configured",
        "live_write_enabled": False,
        "read_only_school_auth": "authorized",
    }


def test_bridge_endpoint_strict_allowlist(monkeypatch):
    monkeypatch.setenv("PMSS_READONLY_BRIDGE_URL","https://malicious.example.com")
    with pytest.raises(ValueError):
        live._readonly_bridge_adapter()
    monkeypatch.delenv("PMSS_READONLY_BRIDGE_URL")
    with pytest.raises(ValueError):
        live._readonly_bridge_adapter()


def test_read_only_preflight_performs_no_school_writes(monkeypatch):
    calls=[]
    monkeypatch.setattr(live, "require_user", lambda req, admin=False: {"role":"admin"})
    monkeypatch.setattr(live, "_catalog", lambda: (
        Path("/tmp"), [{"project_id":"pmss-group-2","name":"课程组2",
                        "cases":[{"case_date":"2025-09-03"}]}]))
    ctx=SimpleNamespace(
        cases=[{"caseDate":"2025-09-03","caseId":"safe-scene"}],
        units=[{"key":"G31-id","title":"G31(燃煤)","mvarate":1050}],
        market_system={"spotList":[{"marketAtomType":"DA"}]},
        day_ahead={"marketAtomType":"DA"},
    )
    class Adapter:
        def list_projects(self,**kw):
            calls.append("list_projects")
            return [{"projectName":"课程组2","projectId":"school-2"}]
        def get_context(self,project):
            calls.append("get_context")
            assert project=="school-2"
            return ctx
        def get_unit_bid(self,**kw):
            calls.append("get_unit_bid")
            return {"datas":[{"segmentDatas":[{}]*5}],
                    "minTechPowerCost":1,"startCostHot":1,
                    "startCostWarm":1,"startCostCold":1}
        def save_unit_bid(self,*args,**kw):
            raise AssertionError("school write attempted")
        def run_clearing(self,*args,**kw):
            raise AssertionError("school clearing attempted")
    monkeypatch.setattr(live, "_readonly_bridge_adapter", lambda: Adapter())
    monkeypatch.setattr(live, "_remote_case", lambda adapter,remote,date,unit:(
        ctx,ctx.cases[0],ctx.units[0],"test-scope"))
    monkeypatch.setattr(live.MarketLimits,"from_pmss", lambda raw:SimpleNamespace(
        same_curve=True,price_floor=0,price_ceiling=1000,max_segments=5))
    result=live.school_preflight(None,"pmss-group-2",date(2025,9,3),"G31-id")
    assert result["school_authenticated"] is True
    assert result["read_only"] is True
    assert result["teacher_write_performed"] is False
    assert result["teacher_clearing_executed"] is False
    assert result["target_unit_name"] == "G31(燃煤)"
    assert result["existing_school_bid_blocks"] == 5
    assert calls == ["list_projects","get_unit_bid"]


def test_preflight_denies_non_admin(monkeypatch):
    def deny(req,admin=False):
        raise HTTPException(status_code=403,detail="admin only")
    monkeypatch.setattr(live,"require_user",deny)
    with pytest.raises(HTTPException) as exc:
        live.school_preflight(None,"pmss-group-2",date(2025,9,3),"G31-id")
    assert exc.value.status_code==403
