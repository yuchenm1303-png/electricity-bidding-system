"""The VPN diagnostic cannot exfiltrate hostnames, cookies or PMSS responses."""
import json
import subprocess
from dataclasses import asdict
from unittest.mock import patch

import pytest

from scripts.diagnose_pmss_connectivity import (
    Probe,
    _head,
    diagnose,
    validate_proxy,
    validate_target,
)


def probe(success: bool, fault: str = "network_timeout") -> Probe:
    return Probe(success, 200 if success else None, 0 if success else 28,
                 "none" if success else fault)


@pytest.mark.parametrize("url", [
    "http://example.test/path?token=not-allowed",
    "http://user:password@example.test/path",
    "http://example.test/#state",
    "file:///etc/passwd",
    "http://example.test:bad/path",
    "http://example.test/path with spaces",
])
def test_reject_embedded_secrets_and_malformed_urls(url):
    with pytest.raises(ValueError):
        validate_target(url)


def test_reject_remote_or_authenticated_proxy():
    for bad in ("socks5h://example.test:1080",
                "socks5h://user:pass@localhost:1080",
                "http://localhost:1080", "socks5h://localhost"):
        with pytest.raises(ValueError):
            validate_proxy(bad)


def test_proxy_works_for_public_but_private_pmss_unreachable(monkeypatch):
    monkeypatch.setattr(
        "scripts.diagnose_pmss_connectivity.shutil.which", lambda _: "/usr/bin/curl"
    )
    monkeypatch.setattr(
        "scripts.diagnose_pmss_connectivity._check_proxy_local",
        lambda *_: True,
    )
    def head(url, *, proxy, timeout):
        if url == "https://example.com":
            return probe(True)
        return probe(False)
    monkeypatch.setattr("scripts.diagnose_pmss_connectivity._head", head)
    report = diagnose("http://private.example.test/pmss/main.html")
    assert report["state"] == "PUBLIC_PROXY_OK_PRIVATE_TARGET_UNREACHABLE"
    assert report["public_via_proxy"]["transport_reachable"] is True
    assert report["pmss_via_proxy"]["transport_reachable"] is False
    assert "private.example.test" not in json.dumps(report)
    assert report["teacher_login_verified"] is False
    assert report["pmss_market_write_performed"] is False


def test_no_proxy_short_circuits_private_proxy_but_checks_direct(monkeypatch):
    monkeypatch.setattr(
        "scripts.diagnose_pmss_connectivity.shutil.which", lambda _: "/usr/bin/curl"
    )
    monkeypatch.setattr(
        "scripts.diagnose_pmss_connectivity._check_proxy_local",
        lambda *_: False,
    )
    def head(url, *, proxy, timeout):
        assert proxy is None
        return probe(True)
    monkeypatch.setattr("scripts.diagnose_pmss_connectivity._head", head)
    report = diagnose("http://private.example.test/")
    assert report["state"] == "LOCAL_PROXY_UNAVAILABLE"
    assert report["pmss_via_proxy"]["curl_exit_code"] == 7


def test_reachable_private_endpoint_is_not_authentication_verification(monkeypatch):
    monkeypatch.setattr(
        "scripts.diagnose_pmss_connectivity.shutil.which", lambda _: "/usr/bin/curl"
    )
    monkeypatch.setattr(
        "scripts.diagnose_pmss_connectivity._check_proxy_local",
        lambda *_: True,
    )
    monkeypatch.setattr(
        "scripts.diagnose_pmss_connectivity._head",
        lambda *_args, **_kwargs: probe(True),
    )
    report = diagnose("https://private.example.test/")
    assert report["state"] == "PRIVATE_ENDPOINT_REACHABLE"
    assert not report["teacher_login_verified"]


def test_uses_head_without_following_redirects_or_logging_remote_address():
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "302", "")
    with patch("scripts.diagnose_pmss_connectivity.subprocess.run", fake_run):
        result = _head(
            "https://private.example.test/pmss/main.html",
            proxy="socks5h://127.0.0.1:11080", timeout=7,
        )
    assert result.transport_reachable
    assert result.http_status == 302
    argv = calls[0]
    assert "--head" in argv
    assert "-L" not in argv and "--location" not in argv
    assert "--output" in argv and "/dev/null" in argv
    assert "token" not in str(argv)


def test_network_timeout_has_stable_diagnostic_code():
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("curl", 10)
    with patch("scripts.diagnose_pmss_connectivity.subprocess.run", timed_out):
        result = _head("https://example.com", proxy=None, timeout=7)
    assert result.curl_exit_code == 28
    assert result.fault_category == "network_timeout"
    assert result.http_status is None


def test_json_schema_is_credential_free(monkeypatch):
    monkeypatch.setattr(
        "scripts.diagnose_pmss_connectivity.shutil.which", lambda _: "/usr/bin/curl"
    )
    monkeypatch.setattr(
        "scripts.diagnose_pmss_connectivity._check_proxy_local",
        lambda *_: True,
    )
    monkeypatch.setattr(
        "scripts.diagnose_pmss_connectivity._head",
        lambda *_args, **_kwargs: probe(False),
    )
    report = diagnose("http://private.example.test/")
    encoded = json.dumps(asdict(probe(False))) + json.dumps(report)
    assert all(token not in encoded for token in (
        "private.example.test", "cookie", "authorization", "password"
    ))
