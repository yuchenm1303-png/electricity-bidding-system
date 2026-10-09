"""Attach case-bound *anonymous* PMSS source evidence to a private snapshot.

Input files must already be authorized and stored under the trusted user's
permissions. This program never logs into PMSS, uses sudo, modifies sources,
overwrites outputs, or includes raw grid/unit records in generated files.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))

from powerbid.pmss_evidence_attachment import attach_pmss_evidence  # noqa: E402


def _load(path: Path, label: str):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label}: input must be an accessible regular file, not a symlink")
    if path.stat().st_size > 16_000_000:
        raise ValueError(f"{label}: input file too large")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline PMSS case-bound evidence attachment")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--technical-grid", type=Path)
    parser.add_argument("--scene-summary", type=Path)
    parser.add_argument("--scene-case-date")
    parser.add_argument("--scene-source-note")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.output.parent.is_dir() or args.output.is_symlink() or args.output.exists():
        parser.error("Output directory must already exist; refusing overwrite/symlink")
    sources = [args.snapshot, args.technical_grid, args.scene_summary]
    if args.output.resolve() in {
        path.resolve() for path in sources if path is not None
    }:
        parser.error("Refusing output/source path alias")

    try:
        market = _load(args.snapshot, "market snapshot")
        grid = _load(args.technical_grid, "technical grid") if args.technical_grid else None
        scene = _load(args.scene_summary, "scene summary") if args.scene_summary else None
        attached = attach_pmss_evidence(
            market, private_grid=grid, scene_summary=scene,
            scene_case_date=args.scene_case_date,
            scene_source_note=args.scene_source_note,
        )
        encoded = json.dumps(
            attached, ensure_ascii=False, allow_nan=False,
            separators=(",", ":"),
        ) + "\n"
        # No temporary open writable from other users, no overwrite and
        # no output after validation failure. O_EXCL is atomic on Linux.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(encoded)
        except BaseException:
            args.output.unlink(missing_ok=True)
            raise
        os.chmod(args.output, stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(
        "Saved private case-bound anonymous PMSS evidence: "
        f"technical={attached.get('technicalEvidence') is not None}, "
        f"scene={attached.get('sceneConstraintEvidence') is not None}. "
        "Binding is an operator integrity assertion, NOT independent PMSS "
        "physical verification. No PMSS login, write or clearing attempted."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
