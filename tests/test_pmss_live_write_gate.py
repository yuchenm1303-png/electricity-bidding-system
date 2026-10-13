"""The original write-gate must reject any request outside two fixed methods."""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from powerbid.adapters.teacher_platform import TeacherPlatformAdapter


def test_write_token_sent_only_for_original_irreversible_posts():
    adapter = TeacherPlatformAdapter(
        base_url="http://172.17.0.1:18760",
        write_gate_token="private-test-gate",
    )
    sent = []
    def fake_request(method, url, **kwargs):
        sent.append((method, url.rsplit("/", 1)[-1], kwargs.get("headers")))
        response = MagicMock(status_code=200)
        response.json.return_value = {"retCode": "T200", "data": {}}
        return response
    adapter.session.request = fake_request
    adapter.list_projects()
    adapter.save_unit_bid({"example": "only-a-mock"}, commit=True)
    adapter.run_clearing(case_id="a", commit=True)
    assert sent[0][2] is None
    assert sent[1][2] == {"X-PowerBid-Write-Gate": "private-test-gate"}
    assert sent[2][2] == {"X-PowerBid-Write-Gate": "private-test-gate"}


def test_write_gate_without_runtime_token_fails_closed(monkeypatch):
    from app import pmss_live_api as live
    monkeypatch.setenv("PMSS_LIVE_GATEWAY_ENABLED", "1")
    monkeypatch.setenv("PMSS_LIVE_GATEWAY_URL", "http://172.17.0.1:18760")
    monkeypatch.setenv("PMSS_LIVE_WRITE_TOKEN_FILE", "/nonexistent/pmss-token")
    monkeypatch.setenv("PMSS_LIVE_PROJECT_MAP_FILE", "/nonexistent/pmss-map")
    with pytest.raises(ValueError):
        live._adapter()


def test_write_gate_binds_only_to_private_gateway(monkeypatch):
    from app import pmss_live_api as live
    monkeypatch.setenv("PMSS_LIVE_GATEWAY_ENABLED", "1")
    monkeypatch.setenv("PMSS_LIVE_GATEWAY_URL", "https://example.invalid/")
    monkeypatch.setenv("PMSS_LIVE_WRITE_TOKEN_FILE", "/tmp/test-token")
    monkeypatch.setenv("PMSS_LIVE_PROJECT_MAP_FILE", "/tmp/test-map")
    assert live._gateway_available() is False


def test_write_gate_body_schema_is_strict(monkeypatch):
    bridge = types.ModuleType("bridge")
    bridge.Handler = type("StubHandler", (), {})
    monkeypatch.setitem(sys.modules, "bridge", bridge)
    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    monkeypatch.syspath_prepend(scripts)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "isolated_pmss_write_gate", Path(scripts) / "pmss_live_gateway.py"
    )
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    valid = {
        "scopeId": "scope", "unitId": "unit", "minTechPowerCost": 1,
        "startCostHot": 1, "startCostWarm": 1, "startCostCold": 1,
        "datas": [{
            "startPeriod": 1, "endPeriod": 24,
            "segmentDatas": [
                {"segmentOrder": i+1, "startPower": i*100,
                 "endPower": (i+1)*100, "price": i*100}
                for i in range(5)
            ],
        }],
    }
    assert gate._valid_bid(valid)
    assert not gate._valid_bid({**valid, "extra": "invalid"})
    assert not gate._valid_bid({**valid, "datas": []})
    assert gate._valid_clearing({"caseId": "a", "comment": "approved"})
    assert not gate._valid_clearing({"caseId": "a", "comment": "approved",
                                    "path": "arbitrary"})
