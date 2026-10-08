"""Parse the PMSS operating-scene day-ahead nodal load input.

Read-only endpoint: POST scene/loadFc/list. Response carries an outer
pagination object: data.periodNum and data.data.datas[].
The day-ahead 24-hour load curve is da.t01..da.t24 on each node.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DayAheadLoads:
    period_num: int
    node_count: int
    total_load_mw: tuple[float, ...]
    source: str = "PMSS operating-scene day-ahead load input (da.t01..t24)"


def parse_da_nodal_loads(payload: Mapping[str, Any]) -> DayAheadLoads:
    if not isinstance(payload, Mapping):
        raise ValueError("PMSS load response must be a JSON object")
    period_num = int(payload.get("periodNum", 0))
    if period_num != 24:
        raise ValueError(f"Expected 24 PMSS periods, got {period_num}")
    page = payload.get("data")
    if not isinstance(page, Mapping) or not isinstance(page.get("datas"), list):
        raise ValueError("PMSS loads require data.datas pagination")
    rows = page["datas"]
    if not rows:
        raise ValueError("PMSS scenario has no nodal load records")
    row_count = int(page.get("rowCount", len(rows)))
    if row_count > len(rows):
        raise ValueError(
            f"PMSS load response is incomplete: {len(rows)}/{row_count} rows"
        )
    seen: set[str] = set()
    totals = [0.0] * 24
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("PMSS node load row must be an object")
        element = str(row.get("elementId") or "")
        if not element or element in seen:
            raise ValueError("Missing or duplicate PMSS load element ID")
        seen.add(element)
        da = row.get("da")
        if not isinstance(da, Mapping):
            raise ValueError(f"PMSS load element {element} missing DA curve")
        for i in range(24):
            key = f"t{i + 1:02d}"
            try:
                val = float(da[key])
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f"PMSS load element missing numeric {key}") from exc
            if not isfinite(val):
                raise ValueError(f"PMSS load element has non-finite {key}")
            totals[i] += val
    if any(value <= 0 for value in totals):
        raise ValueError("PMSS total load must remain positive in every period")
    return DayAheadLoads(
        period_num=period_num,
        node_count=len(rows),
        total_load_mw=tuple(round(value, 8) for value in totals),
    )
