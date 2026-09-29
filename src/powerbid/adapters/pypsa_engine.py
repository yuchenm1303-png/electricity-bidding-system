from __future__ import annotations

from powerbid.models import ClearingResult, MarketScenario


class PyPSAClearingEngine:
    """Single-zone market clearing backed by PyPSA.

    PyPSA is imported lazily so the core MVP stays dependency-free. Install
    with `pip install -e '.[pypsa]'` before selecting this engine.
    """

    def __init__(self, solver_name: str = "highs") -> None:
        self.solver_name = solver_name

    def clear(self, scenario: MarketScenario) -> ClearingResult:
        try:
            import pypsa
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "PyPSA is not installed. Run: pip install -e '.[pypsa]'"
            ) from exc

        total_capacity = sum(offer.quantity_mw for offer in scenario.offers)
        if total_capacity + 1e-9 < scenario.demand_mw:
            accepted = {offer.unit_id: offer.quantity_mw for offer in scenario.offers}
            clearing_price = max((offer.bid_price for offer in scenario.offers), default=None)
            return ClearingResult(
                clearing_price=clearing_price,
                accepted_mw=accepted,
                demand_mw=scenario.demand_mw,
                supplied_mw=total_capacity,
                unserved_mw=scenario.demand_mw - total_capacity,
            )

        network = pypsa.Network()
        network.add("Bus", "market")
        for offer in scenario.offers:
            network.add(
                "Generator",
                offer.unit_id,
                bus="market",
                p_nom=offer.quantity_mw,
                marginal_cost=offer.bid_price,
            )
        network.add("Load", "demand", bus="market", p_set=scenario.demand_mw)

        status, condition = network.optimize(solver_name=self.solver_name)
        if status != "ok":
            raise RuntimeError(f"PyPSA optimization failed: {status} / {condition}")

        dispatch = network.generators_t.p.iloc[0].to_dict()
        accepted = {
            offer.unit_id: max(0.0, float(dispatch.get(offer.unit_id, 0.0)))
            for offer in scenario.offers
        }
        supplied = sum(accepted.values())
        price = float(network.buses_t.marginal_price["market"].iloc[0])

        return ClearingResult(
            clearing_price=price,
            accepted_mw=accepted,
            demand_mw=scenario.demand_mw,
            supplied_mw=supplied,
            unserved_mw=max(0.0, scenario.demand_mw - supplied),
        )
