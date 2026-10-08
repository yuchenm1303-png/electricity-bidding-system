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
    summary = [row for row in rows if row.get("elementName") == "统调负荷"]
    row_count = int(page.get("rowCount", len(rows) - len(summary)))
    if len(summary) > 1:
        raise ValueError("Duplicate PMSS total load summary row")
    nodal_rows = [row for row in rows if row not in summary]
    if len(nodal_rows) != row_count:
        raise ValueError(
            f"PMSS load response is incomplete: {len(nodal_rows)}/{row_count} rows"
        )
    seen: set[str] = set()
    totals = [0.0] * 24
    for row in nodal_rows:
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
    # PMSS returns a separate '统调负荷' total before the 39 Bus rows.
    # Verify consistency, but do not double-count it.
    if summary:
        reported = summary[0].get("da")
        if not isinstance(reported, Mapping):
            raise ValueError("PMSS load summary is missing DA values")
        for i, total in enumerate(totals, 1):
            key = f"t{i:02d}"
            try:
                observed = float(reported[key])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("PMSS total load has missing DA hours") from exc
            if not isfinite(observed) or abs(observed - total) > 0.1:
                raise ValueError(f"PMSS DA load summary does not match node sum: {key}")
    if any(value <= 0 for value in totals):
        raise ValueError("PMSS total load must remain positive in every period")
    return DayAheadLoads(
        period_num=period_num,
        node_count=len(nodal_rows),
        total_load_mw=tuple(round(value, 8) for value in totals),
    )
