"""Read-only PMSS scenario/initial-state export into a private case-bound snapshot.

Requires an existing, authorized PMSS app session. A working campus VPN is
NOT sufficient: T000 means login expired and this tool stops immediately.
Only get_context/get_scene_unit_constraints/get_unit_initial_state_inputs
are allowed. No bids are submitted; no clearing is executed.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.adapters.teacher_platform import (  # noqa: E402
    TeacherPlatformAdapter,
    TeacherPlatformAuthenticationExpired,
    TeacherPlatformError,
)
from powerbid.pmss_scene_evidence_export import (  # noqa: E402
    collect_same_case_scene_evidence,
)


def _private_json(path: Path, *, label: str) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_000_000:
        raise ValueError(f"{label}: require regular accessible JSON, max 16MB")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label}: expected JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export only approved, same-case PMSS scene observations"
    )
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--case-date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    base_url = os.environ.get("PMSS_BASE_URL", "")
    cookie_path = os.environ.get("PMSS_COOKIE_FILE", "")
    if not base_url or not cookie_path:
        parser.error(
            "An authorized PMSS_BASE_URL and PMSS_COOKIE_FILE are required. "
            "Sign in at the official school page first; no password automation."
        )
    if args.output.exists() or args.output.is_symlink() or (
        not args.output.parent.is_dir()
    ):
        parser.error("Output must be a new file inside an existing private directory")
    if args.output.resolve() == args.snapshot.resolve():
        parser.error("Refusing to overwrite or alias the historical snapshot")

    try:
        cookie = Path(cookie_path)
        if cookie.is_symlink() or not cookie.is_file():
            raise ValueError("Private PMSS cookie file is unavailable")
        if cookie.stat().st_mode & 0o077:
            raise ValueError("PMSS cookie file must have owner-only permissions")
        cookies = _private_json(cookie, label="authorized PMSS cookies")
        if not cookies or any(
            type(k) is not str or type(v) is not str
            or not k or not v for k, v in cookies.items()
        ):
            raise ValueError("Private PMSS cookie JSON must map cookie names to values")
        historical = _private_json(args.snapshot, label="private historical snapshot")
        adapter = TeacherPlatformAdapter(
            base_url=base_url,
            proxy_url=os.environ.get("PMSS_PROXY_URL") or None,
            cookies=cookies,
            timeout=12,
        )
        attached = collect_same_case_scene_evidence(
            adapter, historical,
            project_id=args.project_id, case_date=args.case_date,
        )
        data = json.dumps(
            attached, ensure_ascii=False, allow_nan=False,
            separators=(",", ":"),
        ) + "\n"
        if len(data.encode("utf-8")) > 16_000_000:
            raise ValueError("Sanitized output exceeds 16MB")
        fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(data)
        except BaseException:
            args.output.unlink(missing_ok=True)
            raise
        os.chmod(args.output, stat.S_IRUSR | stat.S_IWUSR)
    except TeacherPlatformAuthenticationExpired:
        # No private retMsg, site URL, cookie or response content is emitted.
        print(
            "PMSS application session expired. Reauthenticate in the official "
            "school site; VPN availability alone does not prove app login.",
            file=sys.stderr,
        )
        return 3
    except (TeacherPlatformError, OSError, UnicodeError, ValueError, TypeError, KeyError):
        print(
            "No evidence exported: unavailable/invalid authorized read-only "
            "PMSS source, wrong case, or incomplete scene result. "
            "No bids or clearing attempted.",
            file=sys.stderr,
        )
        return 4
    print(
        "Read-only scene evidence attached to NEW private historical snapshot "
        "(0600). File digest & selected case binding established, NOT teacher "
        "platform physical semantics verification. No PMSS bid/write/clearing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
