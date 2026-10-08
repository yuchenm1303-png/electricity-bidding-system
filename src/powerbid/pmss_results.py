"""Confirmed PMSS 24-hour result decoders.

Observed API: unitBid/listForGd -> {periodNum,datas:[...]};
nodalLmp/list and branchFlow/list -> {period,data:[...]}.
Nodal API calls its price series 'powerFlow'; do not infer meaning from name.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from powerbid.pmss_integration import read_24_values


@dataclass(frozen=True, slots=True)
class NodalPriceResult:
    element_id: str
    name: str
    market_type: str
    lmp: tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class BranchFlowResult:
    element_id: str
    name: str
    market_type: str
    flow_mw: tuple[float | None, ...]
    from_node_price: tuple[float | None, ...]
    to_node_price: tuple[float | None, ...]
    shadow_price: tuple[float | None, ...]
    congestion_surplus: tuple[float | None, ...]


def _validated_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise ValueError("PMSS result payload is not a JSON object")
    if int(payload.get("period", 24)) != 24:
        raise ValueError("Expected PMSS 24-hour result period")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("PMSS result data must be a list")
    if any(not isinstance(row, dict) for row in data):
        raise ValueError("PMSS result contains a non-object row")
    return data


def parse_nodal_prices(payload: Mapping[str, Any]) -> tuple[NodalPriceResult, ...]:
    result = []
    for row in _validated_rows(payload):
        result.append(
            NodalPriceResult(
                element_id=str(row["elementId"]),
                name=str(row["elementName"]),
                market_type=str(row["marketTypeAtom"]),
                lmp=read_24_values(row["powerFlow"], "nodalLmp.powerFlow"),
            )
        )
    return tuple(result)


def parse_branch_flows(payload: Mapping[str, Any]) -> tuple[BranchFlowResult, ...]:
    result = []
    for row in _validated_rows(payload):
        result.append(
            BranchFlowResult(
                element_id=str(row["elementId"]),
                name=str(row["elementName"]),
                market_type=str(row["marketTypeAtom"]),
                flow_mw=read_24_values(row["powerFlow"], "branch.powerFlow"),
                from_node_price=read_24_values(
                    row["beginNodePrice"], "branch.beginNodePrice"
                ),
                to_node_price=read_24_values(
                    row["endNodePrice"], "branch.endNodePrice"
                ),
                shadow_price=read_24_values(
                    row["shadowPrice"], "branch.shadowPrice"
                ),
                congestion_surplus=read_24_values(
                    row["blockSurplus"], "branch.blockSurplus"
                ),
            )
        )
    return tuple(result)
