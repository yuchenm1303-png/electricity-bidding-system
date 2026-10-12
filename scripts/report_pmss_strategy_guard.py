"""Evaluate candidate risk against private, read-only dated PMSS evidence.

Run only on the trusted host with authorized case files. Do not commit input
cases or raw bid curves. The JSON output includes only sanitized aggregates.
Example:
  python scripts/report_pmss_strategy_guard.py \
    --candidates /private/candidate-curves.json --target-unit-id G1 \
    --output /private/candidate-risk-report.json \
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

from powerbid.pmss_strategy_guard import assess_pmss_strategy_candidates  # noqa: E402

MAX_FILE_BYTES = 4 * 1024 * 1024


def _read_json(path: Path):
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Input exceeds private research file size limit")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only independent PMSS date strategy research guard"
    )
    parser.add_argument("snapshots", type=Path, nargs="+")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--target-unit-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-dispatch-mae-mw", type=float, default=20.0)
    parser.add_argument("--max-nodal-price-mae", type=float, default=50.0)
    args = parser.parse_args(argv)
    if not 3 <= len(args.snapshots) <= 5:
        parser.error("Supply exactly 3..5 independently dated historical cases")
    sources = [p.resolve() for p in [*args.snapshots, args.candidates]]
    destination = args.output.resolve()
    if len(set(sources)) != len(sources) or destination in sources or destination.exists():
        parser.error("Repeated source or existing output is prohibited")
    try:
        cases = [_read_json(path) for path in args.snapshots]
        proposals = _read_json(args.candidates)
        if isinstance(proposals, dict):
            proposals = proposals.get("eligible_candidates", proposals.get("candidates"))
        report = assess_pmss_strategy_candidates(
            cases, proposals, args.target_unit_id,
            max_dispatch_mae_mw=args.max_dispatch_mae_mw,
            max_nodal_price_mae=args.max_nodal_price_mae,
        )
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(f"Private candidate audit failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    try:
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
    except OSError as exc:
        print(f"Unable to create private report: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("Read-only candidate risk report generated; no PMSS writes or live approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
