"""Private, anonymized held-out tie-break diagnostic for historical PMSS bids.

Only accepts 3..12 locally available original-bid historical cases. It
does not connect to PMSS or modify any quotes. Never publishes source
generator identifiers, recorded offers, cookies or raw dispatch rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.pmss_tiebreak_holdout import (  # noqa: E402
    evaluate_heldout_tiebreak_rules,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train-day-only tie-break rule selection; held-out original-bid check"
    )
    parser.add_argument("snapshots", type=Path, nargs="+")
    parser.add_argument("--holdout-dates", type=int, default=1)
    parser.add_argument(
        "--min-training-improvement-mw", type=float, default=1.0,
        help="Predeclared minimum paired MAE improvement per training day; not fit on holdout",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 3 <= len(args.snapshots) <= 12:
        parser.error("Require 3..12 private dated original-bid PMSS snapshots")
    if (not args.output.parent.is_dir() or args.output.exists()
            or args.output.is_symlink()):
        parser.error("Output must be a NEW file in an existing private directory")
    if any(path.is_symlink() or not path.is_file() for path in args.snapshots):
        parser.error("Historical inputs must be readable regular files, not symlinks")
    paths = [path.resolve() for path in args.snapshots]
    if len(set(paths)) != len(paths) or args.output.resolve() in paths:
        parser.error("No duplicate or output-alias paths permitted")
    try:
        cases = []
        for path in args.snapshots:
            if path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Historical input exceeds 4 MiB")
            cases.append(json.loads(path.read_text("utf-8")))
        report = evaluate_heldout_tiebreak_rules(
            cases,
            holdout_dates=args.holdout_dates,
            min_training_improvement_mw=args.min_training_improvement_mw,
        )
        # Do not put raw offers, IDs, source paths or data in the report.
        payload = json.dumps(
            report, ensure_ascii=False, indent=2, allow_nan=False
        ) + "\n"
        fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
        except BaseException:
            args.output.unlink(missing_ok=True)
            raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(
            "Historical tie-break holdout evaluation failed: "
            f"{type(exc).__name__}; no PMSS write or clearing.",
            file=sys.stderr,
        )
        return 1
    print(
        "Private historical original-bid holdout: "
        f"{report['trainingCaseCount']} training, "
        f"{report['holdoutCaseCount']} holdout dates. "
        "Candidate-bid PMSS validation and profit prediction remain FALSE."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
