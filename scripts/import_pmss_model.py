"""Import an authorized PMSS DA case to a PRIVATE standard JSON artifact.

Offline mode consumes previously exported read-only files. Live mode invokes
the existing teacher adapter only; no bid save or simulate/execute calls.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.adapters.teacher_platform import TeacherPlatformAdapter  # noqa: E402
from powerbid.pmss_model_import import (  # noqa: E402
    build_standard_pmss_model,
    read_live_standard_pmss_model,
)


def _json_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def _outside_repositories(output: Path) -> None:
    # Do not let an operator accidentally place course data in any Git tree.
    for parent in (output.parent, *output.parents):
        if (parent / ".git").exists():
            raise ValueError("Private PMSS exports cannot be written inside a Git worktree")


def _write_private(output: Path, artifact: dict) -> None:
    target = output.expanduser().resolve()
    if not target.parent.is_dir():
        raise ValueError("Private output parent directory must already exist")
    _outside_repositories(target)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(artifact, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _live(args: argparse.Namespace, grid: dict) -> dict:
    base_url = os.getenv("PMSS_BASE_URL")
    cookie_file = os.getenv("PMSS_COOKIE_FILE")
    project_id = os.getenv("PMSS_PROJECT_ID")
    if not base_url or not cookie_file or not project_id:
        raise ValueError(
            "Live mode needs existing private PMSS_BASE_URL, "
            "PMSS_COOKIE_FILE and PMSS_PROJECT_ID configuration"
        )
    if not args.case_date:
        raise ValueError("Live mode requires explicit --case-date")
    cookies = _json_object(Path(cookie_file))
    if not all(type(k) is str and type(v) is str for k, v in cookies.items()):
        raise ValueError("Private PMSS runtime cookie data has invalid shape")
    adapter = TeacherPlatformAdapter(
        base_url=base_url,
        proxy_url=os.getenv("PMSS_PROXY_URL"),
        cookies=cookies,
    )
    context = adapter.get_context(project_id=project_id)
    matching = [case for case in context.cases if case.get("caseDate") == args.case_date]
    if len(matching) != 1:
        raise ValueError("Case date must select exactly one accessible historical case")
    return read_live_standard_pmss_model(
        adapter,
        context=context,
        case=matching[0],
        private_grid=grid,
        grid_case_date=args.grid_case_date,
        include_scene_evidence=not args.skip_scene_evidence,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and privately import PMSS 39/46/10 24h historical model"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", type=Path, help="Private historical DA snapshot")
    mode.add_argument("--live", action="store_true", help="Existing private PMSS read-only API")
    parser.add_argument("--grid", type=Path, required=True, help="Private PMSS grid input")
    parser.add_argument("--grid-case-date", required=True, help="Explicit grid date YYYY-MM-DD")
    parser.add_argument("--case-date", help="Required date for a live historical case")
    parser.add_argument("--scene-evidence", type=Path, help="Offline aggregate evidence JSON")
    parser.add_argument(
        "--skip-scene-evidence",
        action="store_true",
        help="Live import without unverified constraint evidence",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.live and args.scene_evidence:
        parser.error("--scene-evidence is for offline imports only")
    if not args.live and args.skip_scene_evidence:
        parser.error("--skip-scene-evidence applies only to live imports")
    if args.case_date and args.case_date != args.grid_case_date:
        parser.error("Grid and selected case dates must match")
    # The preflight must occur before any PMSS network read.
    target = args.output.expanduser().resolve()
    if target.exists():
        parser.error("Refusing to overwrite an existing private import")
    try:
        _outside_repositories(target)
        if not target.parent.is_dir():
            raise ValueError("Private output parent directory must already exist")
        grid = _json_object(args.grid)
        if args.live:
            imported = _live(args, grid)
        else:
            evidence = _json_object(args.scene_evidence) if args.scene_evidence else None
            imported = build_standard_pmss_model(
                _json_object(args.snapshot),
                grid,
                grid_case_date=args.grid_case_date,
                scene_constraint_evidence=evidence,
            )
        _write_private(target, imported)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Never echo local data, response bodies, cookies or source paths.
        parser.error(
            f"PMSS private import refused ({type(exc).__name__}); no private source details shown"
        )
    stats = imported["importValidation"]
    print(
        "Private DA model imported and verified: "
        f"{stats['busCount']} buses / {stats['branchCount']} branches / "
        f"{stats['generatorCount']} units / {stats['hours']} hours; "
        f"historical rule-bound warnings={stats['historicalPriceRuleBoundWarnings']}; "
        "physical UC semantics remain unverified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
