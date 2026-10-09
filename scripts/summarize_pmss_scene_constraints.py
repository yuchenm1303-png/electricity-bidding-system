"""Summarize locally provided PMSS read-only scenario query responses.

Inputs must already have been fetched through authorized read-only sources.
This CLI contains no credentials, network access, platform writes or clearing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.pmss_scene_constraint_evidence import (  # noqa: E402
    summarize_scene_constraint_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline PMSS scene calculation/initial-state evidence"
    )
    parser.add_argument("--calculation-json", type=Path, required=True)
    parser.add_argument("--initial-json", type=Path, required=True)
    parser.add_argument("--expected-units", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = summarize_scene_constraint_evidence(
        json.loads(args.calculation_json.read_text(encoding="utf-8")),
        json.loads(args.initial_json.read_text(encoding="utf-8")),
        expected_units=args.expected_units,
    )
    output = args.output.resolve()
    if output.exists():
        parser.error("Refusing to overwrite existing evidence")
    if not output.parent.is_dir():
        parser.error("Output directory must already exist")
    fd = os.open(str(output), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    print(
        "Private read-only evidence prepared: "
        f"{report['constraintRows']} calculation rows, "
        f"{report['initialRows']} initial-state rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
