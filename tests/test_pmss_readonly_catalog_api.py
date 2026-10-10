"""Private PMSS read-only catalog: access control, provenance, and path safety."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_pmss_web_api import _synthetic_network_case  # noqa: E402

from app import account_auth  # noqa: E402
from app.web_server import app  # noqa: E402


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("POWERBID_AUTH_ENABLED", "1")
    monkeypatch.setenv("POWERBID_COOKIE_SECURE", "0")
    monkeypatch.setenv("POWERBID_AUTH_DB_PATH", str(tmp_path / "accounts.sqlite"))
    root = tmp_path / "private_pmss"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("POWERBID_PMSS_READONLY_DIR", str(root))
    with account_auth.connection() as db:
        for name, role in (("student", "member"), ("owner", "admin")):
            db.execute(
                "INSERT INTO users(username,email,password_hash,role,active,created_at) "
                "VALUES(?,?,?,?,1,1)",
                (name, name + "@example.com",
                 account_auth.HASHER.hash("A-long-private-passphrase"), role),
            )
    def login(name: str) -> TestClient:
        api = TestClient(app)
        response = api.post(
            "/api/auth/login",
            headers={"X-PowerBid-Request": "1"},
            json={"username": name, "password": "A-long-private-passphrase"},
        )
        assert response.status_code == 200, response.text
        return api
    return root, login


def populate(root: Path, *, snapshot: dict | None = None):
    market = _synthetic_network_case() if snapshot is None else snapshot
    standard = dict(market)
    standard["schemaVersion"] = "powerbid.pmss.standard.v1"
    standard["importValidation"] = {"physicalUCVerified": False}
    (root / "group_2025-09-01.json").write_text(
        json.dumps(standard, ensure_ascii=False), encoding="utf-8"
    )
    (root / "catalog.json").write_text(json.dumps({
        "projects": [{
            "project_id": "pmss-group-2",
            "name": "授权小组研究项目",
            "cases": [{"case_date": "2025-09-01", "file": "group_2025-09-01.json"}],
        }]
    }, ensure_ascii=False), encoding="utf-8")


def test_readonly_routes_require_admin_and_explicit_configuration(environment, monkeypatch):
    root, login = environment
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/pmss/read-only/projects").status_code == 401
        assert anonymous.get("/api/pmss/read-only/snapshot", params={
            "project_id": "pmss-group-2", "case_date": "2025-09-01",
        }).status_code == 401
    with login("student") as member:
        assert member.get("/api/pmss/read-only/projects").status_code == 403
        assert member.get("/api/pmss/read-only/cases", params={
            "project_id": "pmss-group-2",
        }).status_code == 403
    with login("owner") as admin:
        # Empty private directory cannot turn into a fake connection.
        assert admin.get("/api/pmss/read-only/projects").status_code == 503
        populate(root)
        assert admin.get("/api/pmss/read-only/projects").status_code == 200
        monkeypatch.delenv("POWERBID_PMSS_READONLY_DIR")
        assert admin.get("/api/pmss/read-only/projects").status_code == 503
        monkeypatch.setenv("POWERBID_AUTH_ENABLED", "0")
        assert admin.get("/api/pmss/read-only/projects").status_code == 503


def test_end_to_end_project_date_snapshot_contract(environment):
    root, login = environment
    populate(root)
    with login("owner") as admin:
        p = admin.get("/api/pmss/read-only/projects")
        assert p.status_code == 200, p.text
        assert p.json()["projects"] == [
            {"project_id": "pmss-group-2", "name": "授权小组研究项目"}
        ]
        assert p.headers["cache-control"].startswith("private, no-store")
        cases = admin.get("/api/pmss/read-only/cases", params={
            "project_id": "pmss-group-2",
        })
        assert cases.json()["cases"] == [{
            "case_date": "2025-09-01", "label": "2025-09-01",
        }]
        result = admin.get("/api/pmss/read-only/snapshot", params={
            "project_id": "pmss-group-2", "case_date": "2025-09-01",
        })
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["source_kind"] == "authorized_pmss_read_only"
        assert body["read_only"] is True
        assert body["case_date"] == body["snapshot"]["caseDate"]
        assert "schemaVersion" not in body["snapshot"]
        assert "importValidation" not in body["snapshot"]
        assert len(body["snapshot"]["demandForecastMw"]) == 24
        assert body["snapshot"]["historicalBacktestOnly"] is True
        assert result.headers["cache-control"].startswith("private, no-store")
        assert admin.get("/api/pmss/read-only/snapshot", params={
            "project_id": "unknown", "case_date": "2025-09-01",
        }).status_code == 404
        assert admin.get("/api/pmss/read-only/snapshot", params={
            "project_id": "pmss-group-2", "case_date": "2025-09-02",
        }).status_code == 404


def test_wrong_date_nested_secret_and_catalog_tamper_fail_closed(environment):
    root, login = environment
    populate(root)
    with login("owner") as admin:
        params = {"project_id": "pmss-group-2", "case_date": "2025-09-01"}
        path = root / "group_2025-09-01.json"
        raw = json.loads(path.read_text())
        raw["caseDate"] = "2025-09-02"
        path.write_text(json.dumps(raw), encoding="utf-8")
        assert admin.get("/api/pmss/read-only/snapshot", params=params).status_code == 503
        raw["caseDate"] = "2025-09-01"
        raw["unitBids"]["G30"]["datas"][0]["password"] = "must never leave host"
        path.write_text(json.dumps(raw), encoding="utf-8")
        response = admin.get("/api/pmss/read-only/snapshot", params=params)
        assert response.status_code == 503
        assert "must never leave host" not in response.text
        populate(root)
        doc = json.loads((root / "catalog.json").read_text())
        doc["projects"][0]["cases"][0]["file"] = "../nope.json"
        (root / "catalog.json").write_text(json.dumps(doc))
        assert admin.get("/api/pmss/read-only/projects").status_code == 503
        assert admin.get("/api/pmss/read-only/snapshot", params=params).status_code == 503


def test_file_symlink_and_duplicate_project_are_rejected(environment):
    root, login = environment
    populate(root)
    with login("owner") as admin:
        (root / "group_2025-09-01.json").unlink()
        (root / "group_2025-09-01.json").symlink_to(root / "catalog.json")
        assert admin.get("/api/pmss/read-only/snapshot", params={
            "project_id": "pmss-group-2", "case_date": "2025-09-01",
        }).status_code == 503
        catalog = json.loads((root / "catalog.json").read_text())
        catalog["projects"].append(dict(catalog["projects"][0]))
        (root / "catalog.json").write_text(json.dumps(catalog))
        assert admin.get("/api/pmss/read-only/projects").status_code == 503
