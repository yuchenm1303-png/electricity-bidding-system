"""Write private 0600 anonymized *training-only* PMSS zero-mask audit."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.pmss_nonbinding_mask_research import (  # noqa: E402
    audit_training_only_nonbinding_masks,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline original-offer ex-post mask/tie ambiguity; TRAINING-ONLY"
    )
    parser.add_argument("training_snapshots", type=Path, nargs="+")
    parser.add_argument("--holdout-start-date", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not 2 <= len(args.training_snapshots) <= 12:
        parser.error("Require 2..12 historical training-only snapshots")
    resolved = [p.resolve() for p in args.training_snapshots]
    output = args.output.resolve()
    if (
        len(set(resolved)) != len(resolved)
        or output in resolved
        or args.output.exists()
        or args.output.is_symlink()
        or not args.output.parent.is_dir()
        or output == ROOT
        or ROOT in output.parents
    ):
        parser.error("Refusing duplicate, unsafe or Git-tracked output location")
    try:
        cases = []
        for path in args.training_snapshots:
            if (path.is_symlink() or not path.is_file()
                    or path.stat().st_size > 4 * 1024 * 1024):
                raise ValueError("Historical input must be regular and <=4MiB")
            cases.append(json.loads(path.read_text(encoding="utf-8")))
        report = audit_training_only_nonbinding_masks(
            cases, holdout_start_date=args.holdout_start_date,
        )
        serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(serialized + "\n")
    except (OSError, KeyError, ValueError, TypeError, RuntimeError) as exc:
        print(
            f"Private training-only mask report rejected: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    print(
        f"Saved anonymized training-only historical report for {len(cases)} dates. "
        "No holdout labels read; no teacher PMSS write/clearing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
