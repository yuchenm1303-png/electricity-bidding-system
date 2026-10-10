"""Admin-only PMSS historical case catalog backed by private, sanitized files.

Never connects to PMSS, handles teacher credentials, or writes a teacher bid.
A trusted operator explicitly mounts a read-only private directory and sets
POWERBID_PMSS_READONLY_DIR. Disabled by default, including when PowerBid auth
is disabled. No project data is stored in the public Git repository.
"""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.account_auth import require_user
from app.pmss_api import ALLOWED_ROOT_KEYS, _parse_snapshot

router = APIRouter(prefix="/api/pmss/read-only", tags=["pmss-authorized-read"])
_FILE = re.compile(r"^[a-zA-Z0-9_-]{1,96}\\.json$")
_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
_HEADERS = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Vary": "Cookie",
    "X-Content-Type-Options": "nosniff",
}


class CatalogUnavailable(Exception):
    """Never expose private paths, records, parse errors, or authentication data."""


def _read_json(root: Path, filename: str, limit: int) -> dict[str, Any]:
    if not _FILE.fullmatch(filename):
        raise CatalogUnavailable()
    path = root / filename
    try:
        # Reject symlinks even if they happen to resolve inside the directory.
        if path.is_symlink():
            raise CatalogUnavailable()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > limit:
                raise CatalogUnavailable()
            with os.fdopen(fd, "rb", closefd=False) as stream:
                contents = stream.read(limit + 1)
            if len(contents) > limit:
                raise CatalogUnavailable()
        finally:
            os.close(fd)
        document = json.loads(contents.decode("utf-8"))
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        raise CatalogUnavailable() from exc
    if not isinstance(document, dict):
        raise CatalogUnavailable()
    return document


def _root() -> Path:
    configured = os.environ.get("POWERBID_PMSS_READONLY_DIR", "")
    if not configured or not os.path.isabs(configured):
        raise CatalogUnavailable()
    root = Path(configured)
    if root.is_symlink() or not root.is_dir():
        raise CatalogUnavailable()
    return root


def _date(raw: object) -> str:
    if type(raw) is not str or len(raw) != 10:
        raise CatalogUnavailable()
    try:
        if date.fromisoformat(raw).isoformat() != raw:
            raise CatalogUnavailable()
    except ValueError as exc:
        raise CatalogUnavailable() from exc
    return raw


def _catalog() -> tuple[Path, list[dict[str, Any]]]:
    root = _root()
    document = _read_json(root, "catalog.json", 32_768)
    projects = document.get("projects")
    if set(document) != {"projects"} or not isinstance(projects, list) or len(projects) > 20:
        raise CatalogUnavailable()
    ids: set[str] = set()
    for p in projects:
        if not isinstance(p, dict) or set(p) != {"project_id", "name", "cases"}:
            raise CatalogUnavailable()
        ident, label, cases = p["project_id"], p["name"], p["cases"]
        if (type(ident) is not str or not _ID.fullmatch(ident) or ident in ids
                or type(label) is not str or not 1 <= len(label.strip()) <= 120
                or not isinstance(cases, list) or len(cases) > 35):
            raise CatalogUnavailable()
        ids.add(ident)
        dates: set[str] = set()
        for c in cases:
            if not isinstance(c, dict) or set(c) != {"case_date", "file"}:
                raise CatalogUnavailable()
            d = _date(c["case_date"])
            if d in dates or type(c["file"]) is not str or not _FILE.fullmatch(c["file"]):
                raise CatalogUnavailable()
            dates.add(d)
    return root, projects


def _reply(data: dict[str, Any]) -> JSONResponse:
    return JSONResponse(content=data, headers=_HEADERS)


def _authorized(request: Request) -> None:
    # Membership alone is insufficient: classroom data is restricted to the
    # explicitly provisioned PowerBid admin until per-user PMSS grants exist.
    require_user(request, admin=True)


def _unavailable() -> HTTPException:
    return HTTPException(503, "授权只读案例目录不可用，请由管理员检查私有数据配置")


@router.get("/projects")
def projects(request: Request):
    _authorized(request)
    try:
        _root_path, entries = _catalog()
    except CatalogUnavailable as exc:
        raise _unavailable() from exc
    return _reply({"projects": [
        {"project_id": p["project_id"], "name": p["name"]} for p in entries
    ]})


@router.get("/cases")
def cases(request: Request, project_id: str):
    _authorized(request)
    try:
        _root_path, entries = _catalog()
        project = next((p for p in entries if p["project_id"] == project_id), None)
        if project is None:
            raise HTTPException(404, "此工程未在授权目录中")
    except CatalogUnavailable as exc:
        raise _unavailable() from exc
    return _reply({"cases": [
        {"case_date": item["case_date"], "label": item["case_date"]}
        for item in project["cases"]
    ]})


@router.get("/snapshot")
def snapshot(request: Request, project_id: str, case_date: str):
    _authorized(request)
    try:
        selected_date = _date(case_date)
        root, entries = _catalog()
        project = next((p for p in entries if p["project_id"] == project_id), None)
        if project is None:
            raise HTTPException(404, "此工程未在授权目录中")
        case = next((c for c in project["cases"] if c["case_date"] == selected_date), None)
        if case is None:
            raise HTTPException(404, "此案例日期未获授权")
        document = _read_json(root, case["file"], 700_000)
        if "schemaVersion" in document:
            if document["schemaVersion"] != "powerbid.pmss.standard.v1":
                raise CatalogUnavailable()
            # Standard model metadata is private and is not part of the
            # public client-side research snapshot contract.
            raw = {key: value for key, value in document.items() if key in ALLOWED_ROOT_KEYS}
        else:
            raw = document
        if (raw.get("caseDate") != selected_date
                or raw.get("historicalBacktestOnly") is not True
                or raw.get("loadSourceKind") != "PMSS_DA_SCENE_LOAD_INPUT"
                or not isinstance(raw.get("dcNetwork"), dict)
                or not isinstance(raw.get("results"), dict)):
            raise CatalogUnavailable()
        # Reuse the upload privacy, network, history and semantic checks. Never
        # serve unvalidated contents, even to the admin.
        _parse_snapshot(raw)
    except HTTPException:
        raise
    except (CatalogUnavailable, ValueError, TypeError, KeyError, IndexError) as exc:
        raise _unavailable() from exc
    return _reply({
        "source_kind": "authorized_pmss_read_only",
        "read_only": True,
        "project_id": project_id,
        "case_date": selected_date,
        "snapshot": raw,
    })
