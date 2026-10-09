"""Write ONLY an anonymized, private 0600 PMSS original-bid error profile."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.historical_error_profile import anonymized_error_profile  # noqa: E402
from powerbid.historical_validation import (  # noqa: E402
    ValidationPolicy,
    judge_historical_model,
    validate_historical_day,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private historical hourly DC error profile")
    parser.add_argument("snapshots", type=Path, nargs="+")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-unit-mae-mw", type=float, default=20.0)
    parser.add_argument("--max-nodal-price-mae", type=float, default=50.0)
    parser.add_argument("--holdout-days", type=int, default=1)
    args = parser.parse_args(argv)
    if not 3 <= len(args.snapshots) <= 12:
        parser.error("Require 3..12 dated historical cases")
    if args.output.is_symlink() or args.output.exists() or not args.output.parent.is_dir():
        parser.error("Output must be a new private report path")
    if any(p.is_symlink() or not p.is_file() or p.stat().st_size > 4 * 1024 * 1024
           for p in args.snapshots):
        parser.error("Cases must be regular files no larger than 4MiB")
    paths = [p.resolve() for p in args.snapshots]
    if len(set(paths)) != len(paths) or args.output.resolve() in paths:
        parser.error("Duplicate/overlapping paths are forbidden")
    try:
        policy = ValidationPolicy(
            args.max_unit_mae_mw, args.max_nodal_price_mae,
            min_distinct_dates=3, holdout_dates=args.holdout_days,
        )
        days = [
            validate_historical_day(json.loads(p.read_text(encoding="utf-8")))
            for p in args.snapshots
        ]
        verdict = judge_historical_model(days, policy)
        report = anonymized_error_profile(days, verdict, policy)
        serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.write(serialized + "\n")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(f"Historical profile rejected: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        f"Anonymized 24h historical errors saved for {len(days)} case days; "
        f"research-status={verdict.status}; PMSS write operations=none"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
