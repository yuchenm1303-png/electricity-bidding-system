"""Export a credential-free PMSS snapshot from a trusted host.

This process only calls PMSS GET/read endpoints. Credentials remain in an
external runtime JSON file; never put that file inside the repository.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from powerbid.adapters.teacher_platform import TeacherPlatformAdapter  # noqa: E402
from powerbid.pmss_export import build_readonly_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export sanitized PMSS read-only data")
    parser.add_argument("--forecast-json", required=True, type=Path)
    parser.add_argument("--forecast-source", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--case-date", default=None, help="Select a historical case date")
    args = parser.parse_args()

    base_url = os.getenv("PMSS_BASE_URL")
    cookie_path = os.getenv("PMSS_COOKIE_FILE")
    if not base_url or not cookie_path:
        parser.error("PMSS_BASE_URL and PMSS_COOKIE_FILE must be set in the private host environment")

    cookie_file = Path(cookie_path).resolve()
    if not cookie_file.is_file():
        parser.error("Private PMSS cookie file does not exist")
    cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
    if not isinstance(cookies, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in cookies.items()
    ):
        parser.error("PMSS_COOKIE_FILE must contain a string-to-string JSON cookie object")

    forecast = json.loads(args.forecast_json.read_text(encoding="utf-8"))
    if not isinstance(forecast, list):
        parser.error("--forecast-json must contain a JSON array of 24 numeric load values")

    client = TeacherPlatformAdapter(
        base_url=base_url,
        proxy_url=os.getenv("PMSS_PROXY_URL"),
        cookies=cookies,
    )
    context = client.get_context(os.getenv("PMSS_PROJECT_ID"))
    cases = list(context.cases)
    if args.case_date:
        cases = [c for c in cases if str(c.get("caseDate", "")) == args.case_date]
    if not cases:
        parser.error("No matching PMSS case was found (no writes were attempted)")
    if len(cases) != 1 and not args.case_date:
        parser.error("Multiple cases exist; specify --case-date to avoid selecting the wrong one")

    snapshot = build_readonly_snapshot(
        client,
        context=context,
        case=cases[0],
        demand_forecast_mw=forecast,
        forecast_source=args.forecast_source,
    )
    path = args.output.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace, private file permissions, and no authentication in output.
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".pmss-readonly-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    print(f"Read-only PMSS snapshot saved: {len(snapshot['unitTree'])} units, 24 periods.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
