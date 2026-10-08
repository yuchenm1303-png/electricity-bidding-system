"""Trusted-host only: combine two private READ-only PMSS inputs safely.

Never commit the source network JSON, resulting snapshot, or live credentials.
Example:
python scripts/merge_pmss_grid.py --snapshot /tmp/pmss_readonly.json \
 --grid /srv/powerbid-platform/pmss-grid-snapshot.json \
 --output /tmp/powerbid_grid_case.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from powerbid.pmss_grid_export import sanitize_pmss_grid  # noqa: E402
from powerbid.pmss_integration import snapshot_from_pmss  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Strict PMSS read-only grid merge")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() in {
        args.snapshot.resolve(), args.grid.resolve()
    }:
        parser.error("Output exists or aliases a source; refusing overwrite")
    original = json.loads(args.snapshot.read_text(encoding="utf-8"))
    grid_source = json.loads(args.grid.read_text(encoding="utf-8"))
    snapshot = snapshot_from_pmss(
        unit_tree=original["unitTree"],
        unit_bids=original["unitBids"],
        market_system=original["marketSystem"],
        demand_forecast_mw=original["demandForecastMw"],
        forecast_source=original["forecastSource"],
    )
    grid = sanitize_pmss_grid(grid_source, snapshot=snapshot)
    original["grid"] = grid
    # File permission 0600 and atomic replace. Do not print IDs, raw data,
    # private PMSS object contents, or the JSON body in logs.
    fd, temporary = tempfile.mkstemp(
        prefix=".powerbid-grid-", suffix=".tmp", dir=args.output.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(original, fh, ensure_ascii=False, separators=(",", ":"))
        os.chmod(temporary, 0o600)
        os.replace(temporary, args.output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(
        f"Only local JSON saved. Buses={len(grid['buses'])}, "
        f"branches={len(grid['lines'])}, generators={len(grid['unitBuses'])}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
