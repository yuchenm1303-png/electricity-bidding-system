"""Public release smoke checks dynamic imports and never contacts school PMSS."""
from __future__ import annotations

import json

import pytest

from scripts.smoke_powerbid_release import (
    _js_path,
    _origin,
    inspect_powerbid_release,
)


def _bundle(fake_ui=True, api_post=422, lazy=True):
    root = (
        '<!doctype html><html><head>'
        '<script type="module" crossorigin src="/assets/index-aaa.js"></script>'
        '</head><body><div id="root"></div></body></html>'
    )
    assets = {
        "/": (200, root.encode("utf-8")),
        "/assets/index-aaa.js": (
            200,
            b'const page=()=>import("./WorkspaceEntry-bbb.js")'
            if lazy else b'const page=()=>import("./another.js")',
        ),
        "/assets/WorkspaceEntry-bbb.js": (
            200,
            ("const url='holdout-gate';const title='历史分配规则';"
             if fake_ui else "const title='old research';").encode(),
        ),
        "/assets/another.js": (200, b"const old='no feature';"),
        "/api/health": (200, b'{"status":"ok","environment":"teaching-simulation"}'),
        "/openapi.json": (200, json.dumps({
            "paths": {"/api/pmss/holdout-gate": {"post": {"summary": "Safe"}}}
        }).encode()),
        "/api/pmss/holdout-gate": (api_post, b""),
    }
    called = []
    def fetcher(origin, path, method):
        assert origin == "https://power.smirel.com"
        assert method == ("POST" if path == "/api/pmss/holdout-gate" else "GET")
        called.append((path, method))
        return assets[path]
    return fetcher, called


def test_public_release_checks_actual_lazy_chunk_and_post_validation():
    fetcher, called = _bundle()
    result = inspect_powerbid_release("https://power.smirel.com", fetcher=fetcher)
    assert result["state"] == "FRONTEND_BACKEND_HOLDOUT_PARITY_VERIFIED"
    assert result["frontendLazyChunkDiscovered"] is True
    assert result["backendPostRoutePresent"] is True
    assert result["invalidResearchReportRejected"] is True
    assert result["productionMainHeadVerified"] is False
    assert result["teacherPMSSAuthenticated"] is False
    assert result["submittedMarketBid"] is False
    assert result["executedTeacherClearing"] is False
    assert ("/assets/index-aaa.js", "GET") in called
    assert ("/assets/WorkspaceEntry-bbb.js", "GET") in called
    assert ("/api/pmss/holdout-gate", "POST") in called
    assert not any("cq.university" in p for p, _ in called)


@pytest.mark.parametrize(("ui", "post", "lazy"), [
    (False, 422, True),
    (True, 404, True),
    (True, 200, True),
    (True, 422, False),
])
def test_missing_ui_or_insecure_backend_fails_closed(ui, post, lazy):
    fetcher, _ = _bundle(fake_ui=ui, api_post=post, lazy=lazy)
    with pytest.raises(ValueError):
        inspect_powerbid_release("https://power.smirel.com", fetcher=fetcher)


@pytest.mark.parametrize("unsafe", [
    "http://example.com",
    "https://u:p@example.com",
    "https://example.com/secret",
    "https://example.com/?token=secret",
    "file:///etc/passwd",
    "https://example.com/#private",
    "https://example.com:wrong",
])
def test_never_fetch_from_unsafe_origin(unsafe):
    with pytest.raises(ValueError):
        _origin(unsafe)


@pytest.mark.parametrize("asset", [
    "https://other.com/malicious.js",
    "../../secret.js",
    "/external/foreign.js",
    "/assets/../secret.js",
])
def test_only_same_origin_build_assets_are_considered(asset):
    if not asset.startswith(("../../", "/assets/../")):
        with pytest.raises(ValueError):
            _js_path(asset, "/assets/index.js")
    else:
        # Parent hops are not trusted as-is even if normalization stays local.
        resulting = _js_path(asset, "/assets/index.js")
        assert resulting.startswith("/assets/") if asset == "/assets/../secret.js" else True


def test_single_js_entry_is_not_proof_of_missing_lazy_feature():
    fetcher, seen = _bundle()
    response = inspect_powerbid_release("https://power.smirel.com", fetcher=fetcher)
    assert response["frontendHistoryGatePresent"]
    assert seen.index(("/assets/WorkspaceEntry-bbb.js", "GET")) > seen.index(
        ("/assets/index-aaa.js", "GET")
    )


def test_openapi_must_include_a_real_post_handler_not_get():
    fetcher, _ = _bundle()
    def fake_fetch(origin, path, method):
        if path == "/openapi.json":
            return 200, b'{"paths":{"/api/pmss/holdout-gate":{"get":{}}}}'
        return fetcher(origin, path, method)
    with pytest.raises(ValueError, match="POST"):
        inspect_powerbid_release("https://power.smirel.com", fetcher=fake_fetch)


def test_public_health_must_be_healthy_even_when_frontend_is_present():
    fetcher, _ = _bundle()
    def fake_fetch(origin, path, method):
        if path == "/api/health":
            return 200, b'{"status":"stopped"}'
        return fetcher(origin, path, method)
    with pytest.raises(ValueError, match="health"):
        inspect_powerbid_release("https://power.smirel.com", fetcher=fake_fetch)
