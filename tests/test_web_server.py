"""HTTP contract for the React frontend, backed by real optimization engines."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.web_server import app  # noqa: E402

client = TestClient(app)


def example_payload() -> dict:
    case = client.get("/api/scenario")
    assert case.status_code == 200
    data = case.json()
    return {
        "demand_mw": data["demand_mw"],
        "interval_hours": data["interval_hours"],
        "target_unit_id": data["target_unit_id"],
        "offers": data["offers"],
        "start": 180,
        "stop": 400,
        "step": 10,
        "mode": "single",
        "engine": "uniform",
    }


def test_example_uses_truthful_synthetic_source():
    data = client.get("/api/scenario").json()
    assert data["data_source"] == "synthetic"
    assert len(data["offers"]) == 4


def test_single_mode_returns_real_trials():
    result = client.post("/api/optimize", json=example_payload())
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["mode"] == "single"
    assert payload["count"] == 23
    assert payload["best"]["feasible"] is True
    assert isinstance(payload["best"]["profit"], (float, int))


def test_risk_mode_returns_outcomes():
    data = example_payload()
    data["mode"] = "risk"
    result = client.post("/api/optimize", json=data)
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["mode"] == "risk"
    assert len(payload["best"]["outcomes"]) == 9


def test_invalid_or_oversized_requests_are_rejected():
    payload = example_payload()
    payload["step"] = 0
    assert client.post("/api/optimize", json=payload).status_code == 422
    payload["step"] = 0.1
    assert client.post("/api/optimize", json=payload).status_code == 422


def test_no_duplicate_unit_ids():
    payload = example_payload()
    payload["offers"][1]["unit_id"] = payload["offers"][0]["unit_id"]
    assert client.post("/api/optimize", json=payload).status_code == 422


def test_listing_download_cursor_assets_serve_correct_mime(tmp_path, monkeypatch):
    """The SPA catch-all must never respond with index.html for cursor files."""
    from app import web_server

    monkeypatch.setattr(web_server, "DIST", tmp_path)
    (tmp_path / "listing-studio-download-cursor-v2.js").write_text(
        "window.__cursor_loaded = true;", encoding="utf-8"
    )
    (tmp_path / "listing-studio-cursor-reference-v1.css").write_text(
        ".cursor-follow { opacity: .25; }", encoding="utf-8"
    )

    script = client.get("/listing-studio-download-cursor-v2.js")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert script.text == "window.__cursor_loaded = true;"

    css = client.get("/listing-studio-cursor-reference-v1.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert ".cursor-follow" in css.text
