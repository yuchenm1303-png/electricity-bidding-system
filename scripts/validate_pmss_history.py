"""Batch evaluate sanitized PMSS snapshots without any platform network/write access.

Usage:
python scripts/validate_pmss_history.py \
  --max-unit-mae-mw 20 --max-nodal-price-mae 50 \
  --output /tmp/powerbid-history-diagnostics.json \
  /private/snapshot-2025-09-01.json /private/snapshot-2025-09-02.json ...

All thresholds are research assumptions supplied by the caller.
This never certifies a *new* bidding curve's PMSS settlement.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.historical_validation import (  # noqa: E402
    ValidationPolicy,
    judge_historical_model,
    validate_historical_day,
)

MAX_CASE_BYTES = 4 * 1024 * 1024


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only cross-day DC historical baseline validation"
    )
    parser.add_argument("cases", type=Path, nargs="+", help="1..20 sanitized dated snapshots")
    parser.add_argument("--max-unit-mae-mw", required=True, type=float)
    parser.add_argument("--max-nodal-price-mae", required=True, type=float)
    parser.add_argument("--min-coverage", type=float, default=0.95)
    parser.add_argument("--min-days", type=int, default=3)
    parser.add_argument("--holdout-days", type=int, default=1)
    parser.add_argument("--output", type=Path, help="Optional NEW report file (no overwrites)")
    parsed = parser.parse_args(args)
    if len(parsed.cases) > 20:
        parser.error("Maximum 20 case files per validation")
    if len({str(path.resolve()) for path in parsed.cases}) != len(parsed.cases):
        parser.error("Same case path supplied more than once")
    if parsed.output is not None:
        if parsed.output.exists() or parsed.output.resolve() in {
            item.resolve() for item in parsed.cases
        }:
            parser.error("Refusing to overwrite an input or existing report")

    try:
        policy = ValidationPolicy(
            max_unit_dispatch_mae_mw=parsed.max_unit_mae_mw,
            max_nodal_price_mae=parsed.max_nodal_price_mae,
            min_coverage=parsed.min_coverage,
            min_distinct_dates=parsed.min_days,
            holdout_dates=parsed.holdout_days,
        )
        cases = []
        for path in parsed.cases:
            if path.stat().st_size > MAX_CASE_BYTES:
                raise ValueError(f"Case file exceeds 4 MiB: {path.name}")
            record = json.loads(path.read_text(encoding="utf-8"))
            cases.append(validate_historical_day(record))
        verdict = judge_historical_model(cases, policy)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        # Do not print raw input JSON or credential-related values.
        print(f"Validation rejected: {type(exc).__name__}", file=sys.stderr)
        return 1

    report = {
        "notice": (
            "READ-ONLY historical ORIGINAL-BID DC surrogate validation. "
            "No PMSS clearing/submission. No candidate-bid validation."
        ),
        "policy": asdict(policy),
        "verdict": asdict(verdict),
        "days": [asdict(day) for day in sorted(cases, key=lambda item: item.case_date)],
    }
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if parsed.output is None:
        print(output)
    else:
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            fd = os.open(parsed.output, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(output + "\n")
        except OSError as exc:
            print(f"Could not create private report: {type(exc).__name__}", file=sys.stderr)
            return 1
        print(
            f"Saved {len(cases)} historical baseline diagnostics to {parsed.output}; "
            f"status={verdict.status}. No PMSS write/clearing performed."
        )

    return 0 if verdict.status == "HISTORICAL_BASELINE_WITHIN_TOLERANCE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
