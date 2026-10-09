"""Generate PRIVATE aggregate diagnostics for three or more real PMSS dates.

This is an offline research script: it never calls the teacher website,
submits bids, executes clearing or copies historical raw input to a public
endpoint. All inference uses original recorded offers and the local DC model.

Example:
python scripts/report_pmss_crossday.py --output /private/report.json \
  /private/day1.json /private/day2.json /private/day3.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.pmss_crossday_research import summarize_crossday_history  # noqa: E402

MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Anonymized read-only three-day PMSS research diagnostic"
    )
    parser.add_argument("snapshots", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 3 <= len(args.snapshots) <= 20:
        parser.error("Supply 3..20 historical snapshots")
    resolved = [path.resolve() for path in args.snapshots]
    destination = args.output.resolve()
    if len(set(resolved)) != len(resolved):
        parser.error("Do not supply the same snapshot multiple times")
    if destination in resolved or destination.exists():
        parser.error("Refusing to overwrite an input or an existing output")
    try:
        cases = []
        for path in args.snapshots:
            if path.stat().st_size > MAX_SNAPSHOT_BYTES:
                raise ValueError("A history file exceeds the 4 MiB input limit")
            cases.append(json.loads(path.read_text(encoding="utf-8")))
        report = summarize_crossday_history(cases)
    except (OSError, KeyError, ValueError, TypeError, RuntimeError) as exc:
        # Deliberately never print file bodies, PMSS IDs, URLs or credentials.
        print(
            f"Private PMSS diagnostic failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    try:
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, allow_nan=False)
            fh.write("\n")
    except OSError as exc:
        print(
            f"Cannot write private aggregate report: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    print(
        f"Read-only historical report: {len(report['days'])} dates, "
        "descriptive only, no PMSS writes or clearing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
