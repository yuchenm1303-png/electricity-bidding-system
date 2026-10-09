"""Offline 24h DC+UC strategy study with explicit verified-source boundaries.

Examples:
  python scripts/study_pmss_joint.py --snapshot case.json --inspect
  python scripts/study_pmss_joint.py --snapshot case.json --network grid.json \
    --technical tech.json --technical-source synthetic \
    --technical-description "supplied synthetic test" --target-unit G1

Never contacts the teacher platform; reads only supplied local files.
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

from powerbid.network_dispatch import network_from_dict  # noqa: E402
from powerbid.network_strategy import verify_network_inputs  # noqa: E402
from powerbid.pmss_integration import snapshot_from_pmss  # noqa: E402
from powerbid.pmss_joint_research import (  # noqa: E402
    assess_joint_readiness,
    compare_joint_legal_candidates,
)


def main() -> int:
    p = argparse.ArgumentParser(description="OFFLINE joint 24h DC+UC bid study")
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--network", type=Path)
    p.add_argument("--technical", type=Path)
    p.add_argument("--technical-source", default="")
    p.add_argument("--technical-description", default="")
    p.add_argument("--target-unit")
    p.add_argument("--inspect", action="store_true")
    p.add_argument("--solver-limit", type=float, default=12.0)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    raw = json.loads(args.snapshot.read_text(encoding="utf-8"))
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"], unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    supplied = (
        json.loads(args.technical.read_text(encoding="utf-8"))
        if args.technical else None
    )
    if raw.get("syntheticExample") is True and args.technical_source != "synthetic":
        p.error("Synthetic teaching inputs must be explicitly labeled synthetic")
    readiness = assess_joint_readiness(
        snapshot, supplied, source=args.technical_source
    )
    if args.inspect:
        print(json.dumps(asdict(readiness), ensure_ascii=False, indent=2))
        return 0 if readiness.ready else 2
    if not readiness.ready:
        print(json.dumps(asdict(readiness), ensure_ascii=False, indent=2))
        return 2
    net_raw = (
        json.loads(args.network.read_text(encoding="utf-8"))
        if args.network else raw.get("dcNetwork")
    )
    if net_raw is None:
        p.error("Verified dcNetwork or explicitly supplied network JSON is required")
    network = network_from_dict(net_raw)
    target = args.target_unit or snapshot.units[0].unit_id
    verify_network_inputs(snapshot, network, target)
    result = compare_joint_legal_candidates(
        snapshot, network, supplied, target,
        technical_source=args.technical_source,
        technical_source_description=args.technical_description,
        solver_timeout_seconds=args.solver_limit,
    )
    data = asdict(result)
    if args.output:
        # O_EXCL + 0600: never overwrite another run's research results.
        fd = os.open(str(args.output), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
        print(f"LOCAL_RESEARCH_SAVED {args.output}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
