"""Private 0600 training-only PMSS scene/ramp evidence audit (offline)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.pmss_uc_training_evidence import (  # noqa: E402
    audit_training_scene_and_temporal_evidence,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline PMSS training scenario flags and historical MW deltas"
    )
    parser.add_argument("training_snapshots", nargs="+", type=Path)
    parser.add_argument("--scene-capture", required=True, type=Path)
    parser.add_argument("--holdout-start-date", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not 2 <= len(args.training_snapshots) <= 12:
        parser.error("Require 2..12 historical training snapshots")
    inputs = [*args.training_snapshots, args.scene_capture]
    output = args.output.resolve()
    if (len(set(path.resolve() for path in inputs)) != len(inputs)
            or output in {path.resolve() for path in inputs}
            or args.output.exists() or args.output.is_symlink()
            or not args.output.parent.is_dir()
            or ROOT in output.parents):
        parser.error("Private output must be NEW and outside the public Git tree")
    try:
        for p in inputs:
            if p.is_symlink() or not p.is_file() or p.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Invalid or too-large private input file")
        cases = [json.loads(p.read_text("utf-8")) for p in args.training_snapshots]
        saved = json.loads(args.scene_capture.read_text("utf-8"))
        report = audit_training_scene_and_temporal_evidence(
            cases, saved, holdout_start_date=args.holdout_start_date
        )
        payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload + "\n")
    except (OSError, TypeError, KeyError, ValueError, RuntimeError) as exc:
        print(f"Training scene/UC evidence rejected: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        f"Saved anonymized source-code + temporal report for {len(cases)} training days. "
        "Joint MILP remains blocked. No holdout outcomes or PMSS API touched."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
