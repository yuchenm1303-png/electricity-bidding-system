"""Read-only backtest of a network DC model against historical PMSS outcomes.

Only evaluate the ORIGINAL submitted PMSS bid curve. Do not call a network
surrogate prediction 'verified' for a NEW bid based on old observed results.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import sqrt
from typing import Any

from powerbid.network_dispatch import DcNetwork
from powerbid.network_strategy import NetworkBidResult
from powerbid.pmss_diagnostics import series24


@dataclass(frozen=True, slots=True)
class DCHistoricalComparison:
    target_unit_id: str
    observed_accepted_points: int
    observed_target_price_points: int
    observed_network_node_points: int
    observed_line_flow_points: int
    target_dispatch_mae_mw: float | None
    target_dispatch_rmse_mw: float | None
    target_price_mae: float | None
    nodal_price_mae: float | None
    line_absolute_flow_mae_mw: float | None
    description: str = (
        "historical original-bid DC baseline validation; "
        "not PMSS validation of any new bidding policy"
    )


def _id(row: Mapping[str, Any]) -> str:
    return str(row.get("unit_id") or row.get("element_id") or row.get("elementId") or "")


def compare_dc_baseline_to_pmss(
    network: DcNetwork,
    baseline: NetworkBidResult,
    target_unit_id: str,
    results: Mapping[str, Any],
) -> DCHistoricalComparison:
    """Explicitly align identities and 24 hours, preserving missing coverage."""
    if results.get("marketTypeAtom") != "DA" or int(results.get("periodNum", 0)) != 24:
        raise ValueError("Requires 24-hour historical PMSS DA results")
    if target_unit_id not in network.unit_bus:
        raise ValueError("Target unit has no verified node map")
    if not baseline.name.startswith("PMSS 原始已申报曲线"):
        raise ValueError("Only historical original-bid model baseline can be compared")
    if len(baseline.scenarios) != 1:
        raise ValueError("Historical model validation must use exactly one neutral scenario")
    scenario = baseline.scenarios[0]
    if scenario.name != "normal":
        raise ValueError("Historical model validation must use a neutral scenario")
    hours = scenario.hours
    if len(hours) != 24 or any(row.period != i + 1 for i, row in enumerate(hours)):
        raise ValueError("Baseline result hours must match historical PMSS hours 1..24")

    def indexed(name: str) -> dict[str, Mapping[str, Any]]:
        rows = results.get(name)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"Missing observed PMSS {name}")
        observed = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("PMSS result row is not an object")
            if (row.get("market_type") or row.get("marketTypeAtom")) != "DA":
                raise ValueError("PMSS row market does not match DA")
            ident = _id(row)
            if not ident or ident in observed:
                raise ValueError(f"Missing or duplicate PMSS {name} ID")
            observed[ident] = row
        return observed

    units = indexed("unitResults")
    nodes = indexed("nodalPrices")
    lines = indexed("branchFlows")
    if target_unit_id not in units:
        raise ValueError("Observed PMSS target unit not found")
    if set(nodes) != set(network.buses):
        raise ValueError("Observed PMSS node IDs do not match the verified topology")
    if set(lines) != {line.line_id for line in network.lines}:
        raise ValueError("Observed PMSS line IDs do not match the verified topology")

    target = units[target_unit_id]
    dispatch = series24(target, "accepted_mw", "power")
    prices = series24(target, "clearing_prices", "price")
    nodal = {bus: series24(row, "lmp", "powerFlow") for bus, row in nodes.items()}
    flows = {
        line: series24(row, "flow_mw", "powerFlow")
        for line, row in lines.items()
    }
    dispatch_errors = [
        hours[i].dispatched_mw - actual for i, actual in enumerate(dispatch)
        if actual is not None
    ]
    price_errors = [
        abs(hours[i].target_lmp - actual)
        for i, actual in enumerate(prices) if actual is not None
    ]
    node_errors = [
        abs(hours[i].nodal_prices[bus] - actual)
        for bus, seq in nodal.items()
        for i, actual in enumerate(seq)
        if actual is not None
    ]
    # Absolute-value flow MAE avoids asserting unverified PMSS direction
    # convention. Matching magnitude still does NOT establish same line model.
    flow_errors = [
        abs(abs(hours[i].branch_flows_mw[line]) - abs(actual))
        for line, seq in flows.items()
        for i, actual in enumerate(seq)
        if actual is not None
    ]
    return DCHistoricalComparison(
        target_unit_id=target_unit_id,
        observed_accepted_points=len(dispatch_errors),
        observed_target_price_points=len(price_errors),
        observed_network_node_points=len(node_errors),
        observed_line_flow_points=len(flow_errors),
        target_dispatch_mae_mw=(
            sum(map(abs, dispatch_errors)) / len(dispatch_errors)
            if dispatch_errors else None
        ),
        target_dispatch_rmse_mw=(
            sqrt(sum(x*x for x in dispatch_errors) / len(dispatch_errors))
            if dispatch_errors else None
        ),
        target_price_mae=(
            sum(price_errors) / len(price_errors) if price_errors else None
        ),
        nodal_price_mae=(
            sum(node_errors) / len(node_errors) if node_errors else None
        ),
        line_absolute_flow_mae_mw=(
            sum(flow_errors) / len(flow_errors) if flow_errors else None
        ),
    )
