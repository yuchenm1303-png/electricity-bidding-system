"""Merge private authorized PMSS node/line/load data with a sanitized snapshot.

Never commit either source data or output. Only run on trusted server.
Output is compatible with network_from_dict and the React Studio bridge.
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

from powerbid.pmss_grid_bridge import sanitize_pmss_network  # noqa: E402
from powerbid.pmss_integration import snapshot_from_pmss  # noqa: E402
from powerbid.pmss_scene_constraint_evidence import (  # noqa: E402
    validate_scene_constraint_evidence,
)
from powerbid.pmss_technical_evidence import (  # noqa: E402
    sanitize_pmss_technical_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Allowlisted read-only PMSS network merge")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-technical-evidence", action="store_true")
    parser.add_argument("--scene-constraint-evidence", type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() in {
        args.snapshot.resolve(), args.grid.resolve()
    }:
        parser.error("Refusing to overwrite or alias source file")
    original = json.loads(args.snapshot.read_text(encoding="utf-8"))
    raw_grid = json.loads(args.grid.read_text(encoding="utf-8"))
    snapshot = snapshot_from_pmss(
        unit_tree=original["unitTree"],
        unit_bids=original["unitBids"],
        market_system=original["marketSystem"],
        demand_forecast_mw=original["demandForecastMw"],
        forecast_source=original["forecastSource"],
    )
    network = sanitize_pmss_network(raw_grid, snapshot=snapshot)
    original["dcNetwork"] = network
    if args.include_technical_evidence:
        original["technicalEvidence"] = sanitize_pmss_technical_evidence(
            raw_grid, snapshot=snapshot
        )
    if args.scene_constraint_evidence is not None:
        document = json.loads(
            args.scene_constraint_evidence.read_text(encoding="utf-8")
        )
        validate_scene_constraint_evidence(
            document, expected_units=len(snapshot.units)
        )
        original["sceneConstraintEvidence"] = document
    fd, temporary = tempfile.mkstemp(
        prefix=".powerbid-dc-", suffix=".tmp", dir=args.output.parent
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
        "Saved local read-only network snapshot, "
        f"{len(network['buses'])} buses, {len(network['lines'])} branches, "
        f"{len(network['unitBus'])} generators. No PMSS write or clearing performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
