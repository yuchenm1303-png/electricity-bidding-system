from __future__ import annotations

import json
from pathlib import Path

from powerbid.models import MarketScenario, Offer


def load_scenario(path: str | Path) -> MarketScenario:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    offers = tuple(
        Offer(
            unit_id=str(item["unit_id"]),
            quantity_mw=float(item["quantity_mw"]),
            bid_price=float(item["bid_price"]),
            marginal_cost=float(item.get("marginal_cost", item["bid_price"])),
        )
        for item in payload["offers"]
    )
    return MarketScenario(
        name=str(payload.get("name", Path(path).stem)),
        demand_mw=float(payload["demand_mw"]),
        interval_hours=float(payload.get("interval_hours", 1.0)),
        target_unit_id=str(payload["target_unit_id"]),
        offers=offers,
    )
