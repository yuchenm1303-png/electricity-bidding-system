"""Prepare a strictly allowlisted PMSS snapshot using READ endpoints only."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from powerbid.adapters.teacher_platform import TeacherPlatformAdapter, TeacherPlatformContext
from powerbid.pmss_integration import snapshot_from_pmss

_UNIT_KEYS = (
    "key", "unitId", "title", "name", "leaf",
    "mvarate", "unitType", "pdAdjustMax", "pdAdjustMin", "runningCost",
)
_RULE_KEYS = (
    "marketAtomType", "unitPowerDeclareSegmentConstraint",
    "priceLowerConstraint", "priceUpperConstraint", "useSameBiddingCurve",
)
_COST_KEYS = ("minTechPowerCost", "startCostHot", "startCostWarm", "startCostCold")


def build_readonly_snapshot(
    adapter: TeacherPlatformAdapter,
    *,
    context: TeacherPlatformContext,
    case: Mapping[str, Any],
    demand_forecast_mw: list[float],
    forecast_source: str,
    market_type: str = "DA",
) -> dict[str, Any]:
    """Export unit and rule data only. NEVER export authentication/session data.

    Forecast data must be supplied explicitly by caller; actual results and
    observed generator dispatch are not silently used as forecast demand.
    """
    if market_type != "DA":
        raise ValueError("The initial 24-hour snapshot workflow supports DA only")
    scope_id = context.scope_id(case=dict(case), market_type_atom=market_type)
    units = [
        {k: item[k] for k in _UNIT_KEYS if k in item}
        for item in context.units
    ]
    # Context.units is already a flattened set of leaves.
    for unit in units:
        unit["leaf"] = True

    bids: dict[str, dict[str, Any]] = {}
    for unit in units:
        unit_id = str(unit.get("unitId") or unit["key"])
        observed = adapter.get_unit_bid(scope_id=scope_id, unit_id=unit_id)
        if not isinstance(observed, dict):
            raise ValueError(f"Unexpected bid response for unit {unit_id}")
        bids[unit_id] = {"datas": observed.get("datas")}
        bids[unit_id].update({k: observed[k] for k in _COST_KEYS if k in observed})

    rules = {
        "spotList": [
            {k: row[k] for k in _RULE_KEYS if k in row}
            for row in context.market_system.get("spotList", [])
            if row.get("marketAtomType") == market_type
        ]
    }
    # Run all strict mapping validations before allowing a snapshot to leave
    # the trusted server. No credentials or project IDs are copied.
    snapshot_from_pmss(
        unit_tree=units,
        unit_bids=bids,
        market_system=rules,
        demand_forecast_mw=demand_forecast_mw,
        forecast_source=forecast_source,
        market_type=market_type,
    )
    return {
        "unitTree": units,
        "unitBids": bids,
        "marketSystem": rules,
        "demandForecastMw": list(demand_forecast_mw),
        "forecastSource": forecast_source,
    }
