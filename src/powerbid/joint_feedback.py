"""Historical-only validation of the ORIGINAL joint DC+UC bid baseline.

Observed PMSS outcomes are NEVER used to evaluate a counterfactual candidate
or to supply future prices to the joint solver.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import sqrt
from typing import Any

from powerbid.joint_strategy import JointBidEvaluation
from powerbid.network_dispatch import DcNetwork
from powerbid.pmss_diagnostics import series24
from powerbid.pmss_integration import PMSSSnapshot


@dataclass(frozen=True, slots=True)
class JointHistoricalError:
    target_unit_id: str
    target_dispatch_mae_mw: float | None
    target_dispatch_rmse_mw: float | None
    all_unit_dispatch_mae_mw: float | None
    all_bus_lmp_mae: float | None
    line_flow_magnitude_mae_mw: float | None
    target_points: int
    unit_points: int
    node_points: int
    line_points: int
    label: str = "historical original-bid error only; NOT new-bid PMSS validation"


def _ident(row: Mapping[str, Any]) -> str:
    return str(row.get("unit_id") or row.get("element_id") or row.get("elementId") or "")


def compare_joint_baseline_history(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    baseline: JointBidEvaluation,
    target_unit_id: str,
    actual: Mapping[str, Any],
) -> JointHistoricalError:
    if target_unit_id not in snapshot.bids or target_unit_id not in network.unit_bus:
        raise ValueError("Unknown PMSS target unit ID")
    if (
        baseline.periods != snapshot.bids[target_unit_id]
        or not baseline.name.startswith("PMSS 已申报基线")
    ):
        raise ValueError("Historical metrics require the exact original PMSS bid plan")
    if actual.get("marketTypeAtom") != "DA" or int(actual.get("periodNum", 0)) != 24:
        raise ValueError("Historical data must be matching 24h PMSS DA results")
    matching = [row for row in baseline.scenarios if row.name == "neutral"]
    if len(matching) != 1:
        raise ValueError("Historical baseline requires exactly one neutral scenario")
    simulated = matching[0].market.hours
    if len(simulated) != 24 or any(h.period != i + 1 for i, h in enumerate(simulated)):
        raise ValueError("Missing or disordered 24h baseline results")

    def index_rows(key: str, required: set[str]) -> dict[str, Mapping[str, Any]]:
        rows = actual.get(key)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"PMSS missing observed {key}")
        mapped = {}
        for item in rows:
            if not isinstance(item, Mapping):
                raise ValueError("Historical result row is not an object")
            if (item.get("market_type") or item.get("marketTypeAtom")) != "DA":
                raise ValueError("Historical result market type is not DA")
            unit_id = _ident(item)
            if not unit_id or unit_id in mapped:
                raise ValueError(f"Missing or duplicate historical {key} IDs")
            mapped[unit_id] = item
        if set(mapped) != required:
            raise ValueError(f"Historical {key} IDs do not match verified model IDs")
        return mapped

    unit_results = index_rows("unitResults", set(network.unit_bus))
    node_results = index_rows("nodalPrices", set(network.buses))
    line_results = index_rows(
        "branchFlows", {line.line_id for line in network.lines}
    ) if network.lines else {}

    target_errors = []
    unit_errors = []
    node_errors = []
    line_errors = []

    for unit, row in unit_results.items():
        observed = series24(row, "accepted_mw", "power")
        for i, actual_mw in enumerate(observed):
            if actual_mw is None:
                continue
            error = simulated[i].accepted_by_unit[unit] - actual_mw
            unit_errors.append(error)
            if unit == target_unit_id:
                target_errors.append(error)
    for bus, row in node_results.items():
        observed = series24(row, "lmp", "powerFlow")
        node_errors.extend(
            simulated[i].nodal_prices[bus] - number
            for i, number in enumerate(observed) if number is not None
        )
    for line, row in line_results.items():
        observed = series24(row, "flow_mw", "powerFlow")
        line_errors.extend(
            abs(simulated[i].line_flows_mw[line]) - abs(number)
            for i, number in enumerate(observed) if number is not None
        )

    def mae(values: list[float]) -> float | None:
        return sum(abs(v) for v in values) / len(values) if values else None

    return JointHistoricalError(
        target_unit_id=target_unit_id,
        target_dispatch_mae_mw=mae(target_errors),
        target_dispatch_rmse_mw=(
            sqrt(sum(v*v for v in target_errors) / len(target_errors))
            if target_errors else None
        ),
        all_unit_dispatch_mae_mw=mae(unit_errors),
        all_bus_lmp_mae=mae(node_errors),
        line_flow_magnitude_mae_mw=mae(line_errors),
        target_points=len(target_errors),
        unit_points=len(unit_errors),
        node_points=len(node_errors),
        line_points=len(line_errors),
    )
