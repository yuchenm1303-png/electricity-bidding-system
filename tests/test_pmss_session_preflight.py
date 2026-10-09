"""PMSS session readiness without browser redirects, cookie leaks or writes."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from requests.exceptions import HTTPError

from powerbid.adapters.teacher_platform import (
    TeacherPlatformAdapter,
    TeacherPlatformAuthenticationExpired,
    TeacherPlatformError,
    TeacherPlatformRedirectBlocked,
    validate_pmss_base_url,
)
from scripts import doctor_pmss_session as doctor


class FakeResponse:
    def __init__(self, *, status=200, content=None, text="", fail_json=False):
        self.status_code = status
        self.content = content
        self.text = text
        self.fail_json = fail_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError("fixture HTTP problem")

    def json(self):
        if self.fail_json:
            raise ValueError("fixture not JSON")
        return self.content


def fake_adapter(response: FakeResponse):
    calls = []
    adapter = object.__new__(TeacherPlatformAdapter)
    adapter.api_base = "https://valid.example.test/pmss/web"
    adapter.timeout = 2

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return response

    adapter.session = SimpleNamespace(request=request)
    return adapter, calls


@pytest.mark.parametrize("url", [
    "https://user:password@pmss.example.test/",
    "https://pmss.example.test/path?token=secret",
    "https://pmss.example.test/#session=secret",
    "file:///tmp/pmss",
    "https://pmss.example.test:broken",
    "https://pmss.example.test/safe/../wrong",
    "https://pmss.example.test/white space",
    "https://pmss.example.test\\@localhost/secret",
])
def test_pmss_base_url_rejects_ambiguous_and_secret_bearing_destinations(url):
    with pytest.raises(ValueError):
        validate_pmss_base_url(url)


def test_pmss_base_url_retains_explicit_private_http_or_https_host():
    assert validate_pmss_base_url("http://127.0.0.1:8000/") == (
        "http://127.0.0.1:8000"
    )
    assert validate_pmss_base_url("https://campus.example.test") == (
        "https://campus.example.test"
    )


def test_cookie_bearing_redirect_is_not_followed_or_inspected():
    response = FakeResponse(
        status=302, text="INTERNAL-SECRET",
        content={"retCode": "T200"},
    )
    adapter, calls = fake_adapter(response)
    with pytest.raises(TeacherPlatformRedirectBlocked) as info:
        adapter.list_projects()
    assert "INTERNAL-SECRET" not in str(info.value)
    assert "Location" not in str(info.value)
    assert len(calls) == 1
    assert calls[0][0] == "GET"
    assert calls[0][2]["allow_redirects"] is False


def test_non_json_and_private_pmss_retmsg_are_never_returned_in_errors():
    adapter, calls = fake_adapter(FakeResponse(
        text="PRIVATE-JWT-LIKE-SECRET", fail_json=True,
    ))
    with pytest.raises(TeacherPlatformError) as exc:
        adapter.list_projects()
    assert "PRIVATE-JWT-LIKE-SECRET" not in str(exc.value)
    assert "response text" in str(exc.value)
    assert not calls[0][2]["allow_redirects"]
    adapter, _ = fake_adapter(FakeResponse(
        content={
            "retCode": "T401", "retMsg": "PRIVATE-COOKIE-IS-SECRET",
        },
    ))
    with pytest.raises(TeacherPlatformError) as exc:
        adapter.list_projects()
    assert "PRIVATE-COOKIE-IS-SECRET" not in str(exc.value)
    assert "T401" in str(exc.value)
    adapter, _ = fake_adapter(FakeResponse(content=["not", "a", "dict"]))
    with pytest.raises(TeacherPlatformError, match="non-object"):
        adapter.list_projects()


def test_http_401_and_403_do_not_retry_or_expose_private_body():
    for status in (401, 403):
        adapter, calls = fake_adapter(FakeResponse(
            status=status, text="SUPER-SECRET-LOGIN-RESPONSE",
        ))
        with pytest.raises(TeacherPlatformError) as exc:
            adapter.list_projects()
        assert f"HTTP {status}" in str(exc.value)
        assert "SUPER-SECRET" not in str(exc.value)
        assert len(calls) == 1


def test_t000_is_a_distinct_non_retried_app_auth_state():
    adapter, calls = fake_adapter(FakeResponse(
        content={"retCode": "T000", "retMsg": "PRIVATE SECRET"},
    ))
    with pytest.raises(TeacherPlatformAuthenticationExpired):
        adapter.list_projects()
    assert len(calls) == 1


def test_get_context_specific_project_uses_bounded_pagination():
    adapter = object.__new__(TeacherPlatformAdapter)
    requests = []

    def projects(*, page_no=1, page_size=20):
        requests.append(("page", page_no, page_size))
        if page_no == 1:
            return [{"projectId": f"other-{idx}"} for idx in range(50)]
        return [{"projectId": "desired", "tmSceneId": "s", "netId": "n"}]

    adapter.list_projects = projects
    adapter.list_cases = lambda project_id: requests.append(
        ("case", project_id)
    ) or []
    adapter.get_market_system = lambda scene: requests.append(
        ("market", scene)
    ) or {}
    adapter.get_unit_tree = lambda **kwargs: requests.append(
        ("unit_tree", kwargs["project_id"])
    ) or []
    context = adapter.get_context("desired")
    assert context.project["projectId"] == "desired"
    assert requests[:2] == [("page", 1, 50), ("page", 2, 50)]
    assert requests[2:] == [
        ("case", "desired"), ("market", "s"), ("unit_tree", "desired"),
    ]


def test_bounded_project_lookup_never_selects_a_different_first_project():
    adapter = object.__new__(TeacherPlatformAdapter)
    pages = []
    def fake_list(*, page_no=1, page_size=20):
        pages.append(page_no)
        return [{"projectId": f"other-{i}"} for i in range(50)]
    adapter.list_projects = fake_list
    with pytest.raises(TeacherPlatformError, match="not accessible"):
        adapter.find_accessible_project("my-project")
    assert pages == list(range(1, 11))
    with pytest.raises(ValueError):
        adapter.find_accessible_project("my-project", max_pages=11)


def _config(tmp_path, *, cookie_mode=0o600):
    cookie = tmp_path / "pmss-cookie.json"
    cookie.write_text(json.dumps({"PMSSSESSION": "safe_opaque_cookie"}))
    cookie.chmod(cookie_mode)
    return {
        "PMSS_BASE_URL": "https://authorized.example.test",
        "PMSS_COOKIE_FILE": str(cookie),
    }


def test_doctor_missing_configuration_returns_safe_json_not_network():
    status, report = doctor.check_session(
        "SECRET_PROJECT_123", case_date="2025-09-01", environ={},
    )
    assert status == 2
    assert report["state"] == "NOT_CONFIGURED"
    assert report["no_pmss_bid_write"]
    assert "SECRET_PROJECT_123" not in json.dumps(report)


@pytest.mark.parametrize("bad_configuration", [
    {"PMSS_BASE_URL": "https://other.invalid?token=NOPE"},
    {"PMSS_COOKIE_FILE": "/tmp/NO_SUCH_FILE"},
    {"PMSS_PROXY_URL": "socks5h://attacker.test:1080"},
])
def test_doctor_bad_local_settings_short_circuit_before_network(
    tmp_path, monkeypatch, bad_configuration,
):
    config = _config(tmp_path) | bad_configuration
    monkeypatch.setattr(
        doctor, "TeacherPlatformAdapter",
        lambda **kw: pytest.fail("Bad configuration reached PMSS adapter"),
    )
    status, result = doctor.check_session("selected", environ=config)
    assert status == 7
    assert result["state"] == "INVALID_LOCAL_CONFIGURATION"
    assert "safe_opaque_cookie" not in json.dumps(result)


def test_doctor_authenticates_only_explicit_project_and_exact_day(
    tmp_path, monkeypatch,
):
    calls = []
    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(("constructor", kwargs["base_url"]))
        def find_accessible_project(self, project_id):
            calls.append(("project", project_id))
            return {"projectId": project_id}
        def list_cases(self, project_id):
            calls.append(("cases", project_id))
            return [{"caseDate": "2025-09-01"}]
        def run_clearing(self, *args, **kwargs):
            raise AssertionError("MUST NOT CLEAR")
        def save_unit_bid(self, *args, **kwargs):
            raise AssertionError("MUST NOT SAVE")

    monkeypatch.setattr(doctor, "TeacherPlatformAdapter", FakeClient)
    status, report = doctor.check_session(
        "only-selected", case_date="2025-09-01",
        environ=_config(tmp_path),
    )
    assert status == 0
    assert report["state"] == "PMSS_SESSION_AND_CASE_READABLE"
    assert report["pmss_app_session_authenticated"]
    assert report["selected_case_date_present"]
    assert calls == [
        ("constructor", "https://authorized.example.test"),
        ("project", "only-selected"), ("cases", "only-selected"),
    ]
    assert "only-selected" not in json.dumps(report)


def test_doctor_expired_session_and_blocked_redirect_are_distinct(
    tmp_path, monkeypatch,
):
    class ExpiredClient:
        def __init__(self, **kwargs):
            pass
        def find_accessible_project(self, project_id):
            raise TeacherPlatformAuthenticationExpired("T000 SECRET")

    monkeypatch.setattr(doctor, "TeacherPlatformAdapter", ExpiredClient)
    status, result = doctor.check_session(
        "selected", environ=_config(tmp_path),
    )
    assert status == 3
    assert result["state"] == "PMSS_APP_LOGIN_EXPIRED"
    assert "SECRET" not in json.dumps(result)

    class RedirectClient(ExpiredClient):
        def find_accessible_project(self, project_id):
            raise TeacherPlatformRedirectBlocked("PRIVATE-LOCATION")

    monkeypatch.setattr(doctor, "TeacherPlatformAdapter", RedirectClient)
    status, result = doctor.check_session(
        "selected", environ=_config(tmp_path),
    )
    assert status == 4
    assert result["state"] == "REDIRECT_BLOCKED_LOGIN_UNVERIFIED"
    assert "PRIVATE-LOCATION" not in json.dumps(result)


def test_doctor_does_not_accept_unsafe_cookie_file(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "TeacherPlatformAdapter",
                        lambda **kw: pytest.fail("Network must not start"))
    status, report = doctor.check_session(
        "selected", environ=_config(tmp_path, cookie_mode=0o644),
    )
    assert status == 7
    assert report["state"] == "INVALID_LOCAL_CONFIGURATION"
