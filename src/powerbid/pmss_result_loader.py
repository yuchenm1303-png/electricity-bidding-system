"""Read-only loader for the three confirmed PMSS market-result tabs."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from powerbid.adapters.teacher_platform import TeacherPlatformAdapter
from powerbid.pmss_integration import parse_unit_clearing, selected_leaf_ids
from powerbid.pmss_results import parse_branch_flows, parse_nodal_prices


def read_market_results(
    adapter: TeacherPlatformAdapter,
    *,
    case_id: str,
    market_type: str = "DA",
) -> dict[str, Any]:
    """Load actual PMSS results without saving bids or executing clearing.

    PMSS trees use UI keys 'DA-<id>'/'RT-<id>', but its POST filters require
    bare element IDs. This function converts IDs before querying results.
    """
    if market_type not in {"DA", "RT"}:
        raise ValueError("market_type must be DA or RT")
    trees = {
        "unit": adapter.get_unit_result_tree(case_id),
        "node": adapter.get_nodal_tree(case_id),
        "branch": adapter.get_branch_tree(case_id),
    }
    ids = {kind: selected_leaf_ids(tree, market_type) for kind, tree in trees.items()}
    for kind, selected in ids.items():
        if not selected:
            raise ValueError(f"Empty {market_type} PMSS selector for {kind}")
    params = {
        kind: {
            "case_id": case_id,
            "da_ids": selected if market_type == "DA" else [],
            "rt_ids": selected if market_type == "RT" else [],
        }
        for kind, selected in ids.items()
    }
    units = parse_unit_clearing(adapter.get_unit_results(**params["unit"]))
    nodes = parse_nodal_prices(adapter.get_nodal_prices(**params["node"]))
    branches = parse_branch_flows(adapter.get_branch_flows(**params["branch"]))
    expected = {"unit": len(ids["unit"]), "node": len(ids["node"]), "branch": len(ids["branch"])}
    received = {"unit": len(units), "node": len(nodes), "branch": len(branches)}
    # Empty/incomplete results are not presented as a successful full load.
    for kind in expected:
        if received[kind] != expected[kind]:
            raise ValueError(
                f"PMSS {market_type} {kind}: selected {expected[kind]}, "
                f"received {received[kind]} rows"
            )
    return {
        "marketTypeAtom": market_type,
        "periodNum": 24,
        "unitResults": [asdict(row) for row in units],
        "nodalPrices": [asdict(row) for row in nodes],
        "branchFlows": [asdict(row) for row in branches],
    }
