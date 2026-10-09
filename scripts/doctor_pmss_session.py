"""Read-only PMSS application-session preflight. Never sends market writes.

A working VPN is NOT an authenticated PMSS browser session. Check via a
bounded, explicit-project GET listing, optionally a case-date GET. This
doctor NEVER prints URLs, IDs, cookies, server retMsg or raw project data.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.adapters.teacher_platform import (  # noqa: E402
    TeacherPlatformAdapter,
    TeacherPlatformAuthenticationExpired,
    TeacherPlatformError,
    TeacherPlatformRedirectBlocked,
    validate_pmss_base_url,
)
from powerbid.pmss_connectivity_diagnostics import validate_proxy  # noqa: E402
from powerbid.pmss_scene_evidence_export import _case_date, _ident  # noqa: E402

COOKIE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _read_private_cookie_file(raw_path: str) -> dict[str, str]:
    if type(raw_path) is not str or not raw_path:
        raise ValueError("Authorized cookie filename must be explicitly set")
    path = Path(raw_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Session file is missing or a symlink")
    mode = path.stat()
    if mode.st_mode & 0o077 or not 0 < mode.st_size <= 64_000:
        raise ValueError("Session file must be owner-only and <=64KB")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or not parsed or len(parsed) > 50:
        raise ValueError("Cookie file must be a bounded JSON name-value object")
    if any(
        type(name) is not str or not COOKIE_NAME.fullmatch(name)
        or type(value) is not str or not 1 <= len(value) <= 4096
        or any(ord(c) < 33 or ord(c) > 126 for c in value)
        for name, value in parsed.items()
    ):
        raise ValueError("Session file contains invalid cookie entries")
    return parsed


def _result(state: str, action: str, *, auth=False, project=False, case=False):
    return {
        "state": state,
        "safe_action": action,
        "pmss_app_session_authenticated": auth,
        "selected_project_accessible": project,
        "selected_case_date_present": case,
        "queries_are_read_only": True,
        "no_pmss_bid_write": True,
        "no_pmss_clearing_execution": True,
        "identifiers_or_credentials_disclosed": False,
    }


def check_session(
    project_id: str, *,
    case_date: str | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[int, dict]:
    """Only approved GET project-list/case-list endpoints after local checks."""
    config = dict(os.environ) if environ is None else environ
    if not config.get("PMSS_BASE_URL") or not config.get("PMSS_COOKIE_FILE"):
        return 2, _result(
            "NOT_CONFIGURED",
            "Provide official PMSS_BASE_URL and private owner-only PMSS_COOKIE_FILE; "
            "log in via the school's authorized page, not the VPN alone.",
        )
    try:
        _ident(project_id, "Selected project ID")
        if case_date is not None:
            _case_date(case_date)
        base = validate_pmss_base_url(config["PMSS_BASE_URL"])
        proxy = config.get("PMSS_PROXY_URL") or None
        if proxy is not None:
            validate_proxy(proxy)
        cookies = _read_private_cookie_file(config["PMSS_COOKIE_FILE"])
    except (ValueError, TypeError, OSError, UnicodeError, json.JSONDecodeError):
        return 7, _result(
            "INVALID_LOCAL_CONFIGURATION",
            "Check official host URL, local SOCKS proxy, cookie file owner-only "
            "permissions and explicit project/date values. No network query made.",
        )
    try:
        client = TeacherPlatformAdapter(
            base_url=base, proxy_url=proxy, cookies=cookies, timeout=8
        )
        client.find_accessible_project(project_id)
    except TeacherPlatformAuthenticationExpired:
        return 3, _result(
            "PMSS_APP_LOGIN_EXPIRED",
            "Reauthenticate at the official PMSS login page. VPN health "
            "does not mean the application session is valid.",
        )
    except TeacherPlatformRedirectBlocked:
        return 4, _result(
            "REDIRECT_BLOCKED_LOGIN_UNVERIFIED",
            "PMSS redirected a cookie-bearing request. Sign in at the "
            "official site; redirects are never followed with credentials.",
        )
    except (TeacherPlatformError, OSError, ValueError, TypeError):
        return 5, _result(
            "AUTH_OR_PROJECT_UNVERIFIED",
            "The selected PMSS project was not verifiably accessible via "
            "the authorized read-only API; check session, project and VPN.",
        )
    if case_date is None:
        return 0, _result(
            "PMSS_SESSION_PROJECT_READABLE",
            "The PMSS app session read the selected project; to export a "
            "case, additionally verify its exact case date and unit IDs.",
            auth=True, project=True,
        )
    try:
        cases = client.list_cases(project_id)
        matches = [
            item for item in cases if isinstance(item, dict)
            and item.get("caseDate") == case_date
        ]
    except TeacherPlatformAuthenticationExpired:
        return 3, _result(
            "PMSS_APP_LOGIN_EXPIRED",
            "PMSS session expired between read-only requests; sign in again.",
        )
    except TeacherPlatformRedirectBlocked:
        return 4, _result(
            "REDIRECT_BLOCKED_LOGIN_UNVERIFIED",
            "PMSS returned a redirect during case lookup; no cookie forwarding.",
        )
    except (TeacherPlatformError, OSError, ValueError, TypeError):
        return 5, _result(
            "CASE_QUERY_UNAVAILABLE",
            "Could not verify selected case via read-only GET. "
            "Recheck current project and PMSS session.",
            auth=True, project=True,
        )
    if len(matches) != 1:
        return 6, _result(
            "CASE_DATE_MISSING_OR_AMBIGUOUS",
            "The selected project did not have exactly one case on that date. "
            "Do not guess or use the first available case.",
            auth=True, project=True,
        )
    return 0, _result(
        "PMSS_SESSION_AND_CASE_READABLE",
        "Read-only app/project/date checks succeeded; generator identity "
        "and scene-data coverage will still be verified by the exporter.",
        auth=True, project=True, case=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="No-write PMSS application auth and project/day doctor"
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--case-date")
    arguments = parser.parse_args(argv)
    status, result = check_session(
        arguments.project_id, case_date=arguments.case_date,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
