"""Independent DC (lossless) nodal market clearing for OFFLINE strategy research.

This does not claim to implement PMSS's actual AC/SCUC engine. Requires a
verified bus/line topology, generator-node map, and 24 hourly *nodal* demand
series. No credentials, platform calls, bid writes, or clearing execution.

Model: generation - net exports = consumption at every bus, and
f_line = (base_MVA/reactance_pu) * (theta_from - theta_to).
Hourly linear programming optimizes submitted *offer* prices. Its equality
duals are lossless DC nodal marginal prices, NOT observed PMSS prices.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class DcLine:
    line_id: str
    from_bus: str
    to_bus: str
    reactance_pu: float
    limit_mw: float

    def __post_init__(self) -> None:
        if not self.line_id or not self.from_bus or not self.to_bus:
            raise ValueError("Line and bus IDs must not be blank")
        if self.from_bus == self.to_bus:
            raise ValueError("Self-connected line is invalid")
        if any(
            isinstance(v, bool) or not isfinite(v) or v <= 0
            for v in (self.reactance_pu, self.limit_mw)
        ):
            raise ValueError("Line reactance and MW limit must be positive and finite")


@dataclass(frozen=True, slots=True)
class DcNetwork:
    buses: tuple[str, ...]
    lines: tuple[DcLine, ...]
    unit_bus: Mapping[str, str]
    hourly_demand_mw: Mapping[str, tuple[float, ...]]
    slack_bus: str
    base_mva: float
    topology_source: str
    demand_source: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.buses) <= 150:
            raise ValueError("Provide 1..150 buses")
        if len(set(self.buses)) != len(self.buses) or any(not b for b in self.buses):
            raise ValueError("Duplicate or blank bus ID")
        if not 0 <= len(self.lines) <= 250:
            raise ValueError("Too many lines")
        if len({x.line_id for x in self.lines}) != len(self.lines):
            raise ValueError("Duplicate line ID")
        if isinstance(self.base_mva, bool) or not isfinite(self.base_mva):
            raise ValueError("base_mva must be positive and finite")
        if self.base_mva <= 0:
            raise ValueError("base_mva must be positive and finite")
        if not self.topology_source.strip() or not self.demand_source.strip():
            raise ValueError("Verified topology_source and demand_source are required")
        if self.slack_bus not in self.buses:
            raise ValueError("Slack bus not found in network")
        known = set(self.buses)
        if set(self.hourly_demand_mw) != known:
            raise ValueError("Every bus must have exactly one 24h demand series")
        if not self.unit_bus or not all(self.unit_bus):
            raise ValueError("At least one explicitly mapped generator is required")
        if any(bus not in known for bus in self.unit_bus.values()):
            raise ValueError("A mapped generator bus is unknown")
        for bus, hourly in self.hourly_demand_mw.items():
            if len(hourly) != 24:
                raise ValueError(f"Bus {bus} requires exactly 24 load values")
            if any(
                isinstance(x, bool) or not isfinite(x) or x < 0
                for x in hourly
            ):
                raise ValueError(f"Bus {bus} load must be finite and non-negative")
        adjacent = {node: set() for node in self.buses}
        for line in self.lines:
            if line.from_bus not in known or line.to_bus not in known:
                raise ValueError("Branch endpoint not found in bus set")
            adjacent[line.from_bus].add(line.to_bus)
            adjacent[line.to_bus].add(line.from_bus)
        visited: set[str] = set()
        to_visit = [self.slack_bus]
        while to_visit:
            current = to_visit.pop()
            if current not in visited:
                visited.add(current)
                to_visit.extend(adjacent[current] - visited)
        if visited != known:
            raise ValueError("Disconnected buses: DC solver requires a connected network")


@dataclass(frozen=True, slots=True)
class DcOffer:
    unit_id: str
    block: int
    quantity_mw: float
    price: float

    def __post_init__(self) -> None:
        if not self.unit_id or self.block < 1:
            raise ValueError("Offer requires unit ID and positive block number")
        if any(
            isinstance(value, bool) or not isfinite(value) or value < 0
            for value in (self.quantity_mw, self.price)
        ):
            raise ValueError("Quantity and price must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class DcClearing:
    period: int
    accepted_by_unit: dict[str, float]
    accepted_by_block: dict[tuple[str, int], float]
    nodal_prices: dict[str, float]
    line_flows_mw: dict[str, float]
    clearing_offer_cost: float
    served_mw: float
    demand_mw: float
    model_label: str = "offline linear lossless DC dispatch; not PMSS clearing"


class DcInfeasibleError(ValueError):
    """Offline nodal load cannot be served with the supplied network and offers."""


def dc_clear_hour(
    network: DcNetwork,
    offers: Sequence[DcOffer],
    period: int,
    *,
    load_multiplier: float = 1.0,
    time_limit_seconds: float = 12.0,
) -> DcClearing:
    """Solve hourly bid-based DC dispatch with explicit thermal line limits.

    Duals are derived from node load-balance equalities with the convention
    generation - net_exports = demand. The marginal derivative of minimum
    offer-cost with respect to nodal demand is the reported nodal price.
    """
    if not 1 <= period <= 24:
        raise ValueError("period must be 1..24")
    if (
        not isfinite(load_multiplier) or load_multiplier <= 0
        or not isfinite(time_limit_seconds) or time_limit_seconds <= 0
    ):
        raise ValueError("Invalid load multiplier or time limit")
    if not 1 <= len(offers) <= 800:
        raise ValueError("Provide 1..800 valid supply offer bands")
    indices = [(offer.unit_id, offer.block) for offer in offers]
    if len(set(indices)) != len(indices):
        raise ValueError("Duplicate unit/block offer")
    if any(offer.unit_id not in network.unit_bus for offer in offers):
        raise ValueError("Unmapped generator in market offers")
    if set(network.unit_bus) != {offer.unit_id for offer in offers}:
        raise ValueError("Every mapped generator must submit an offer")

    try:
        import numpy as np
        from scipy.optimize import linprog
        from scipy.sparse import lil_matrix
    except ImportError as exc:
        raise RuntimeError(
            "DC market solver requires SciPy: pip install -e '.[strategy]'"
        ) from exc

    nb = len(network.buses)
    no = len(offers)
    nl = len(network.lines)
    buses = {bus: index for index, bus in enumerate(network.buses)}
    angle_nodes = [bus for bus in network.buses if bus != network.slack_bus]
    angle_idx = {bus: no + index for index, bus in enumerate(angle_nodes)}
    line_start = no + len(angle_nodes)
    size = line_start + nl
    cost = np.zeros(size, dtype=float)
    lower: list[float | None] = []
    upper: list[float | None] = []
    for i, offer in enumerate(offers):
        cost[i] = offer.price
        lower.append(0.0)
        upper.append(offer.quantity_mw)
    lower.extend([None] * len(angle_nodes))
    upper.extend([None] * len(angle_nodes))
    lower.extend(-line.limit_mw for line in network.lines)
    upper.extend(line.limit_mw for line in network.lines)
    equations = lil_matrix((nb + nl, size), dtype=float)
    right = np.zeros(nb + nl, dtype=float)
    for bus, index in buses.items():
        right[index] = network.hourly_demand_mw[bus][period - 1] * load_multiplier
    for i, offer in enumerate(offers):
        equations[buses[network.unit_bus[offer.unit_id]], i] = 1.0
    for i, line in enumerate(network.lines):
        flow_column = line_start + i
        equations[buses[line.from_bus], flow_column] -= 1.0
        equations[buses[line.to_bus], flow_column] += 1.0
        equations[nb + i, flow_column] = 1.0
        coefficient = network.base_mva / line.reactance_pu
        if line.from_bus != network.slack_bus:
            equations[nb + i, angle_idx[line.from_bus]] -= coefficient
        if line.to_bus != network.slack_bus:
            equations[nb + i, angle_idx[line.to_bus]] += coefficient

    result = linprog(
        cost,
        A_eq=equations.tocsr(),
        b_eq=right,
        bounds=list(zip(lower, upper, strict=True)),
        method="highs",
        options={"time_limit": time_limit_seconds},
    )
    if result.status == 2:
        raise DcInfeasibleError(
            f"Network-constrained clearing cannot meet demand in period {period}"
        )
    if result.status != 0 or result.x is None:
        raise RuntimeError(
            f"DC dispatch solver did not reach optimality: {result.message}"
        )
    by_unit = {unit: 0.0 for unit in network.unit_bus}
    blocks: dict[tuple[str, int], float] = {}
    for i, offer in enumerate(offers):
        accepted = max(0.0, float(result.x[i]))
        by_unit[offer.unit_id] += accepted
        blocks[(offer.unit_id, offer.block)] = accepted
    flow = {
        line.line_id: float(result.x[line_start + i])
        for i, line in enumerate(network.lines)
    }
    lmp = {
        bus: float(result.eqlin.marginals[index])
        for bus, index in buses.items()
    }
    return DcClearing(
        period=period,
        accepted_by_unit=by_unit,
        accepted_by_block=blocks,
        nodal_prices=lmp,
        line_flows_mw=flow,
        clearing_offer_cost=float(result.fun),
        served_mw=sum(by_unit.values()),
        demand_mw=float(sum(right[:nb])),
    )


def network_from_dict(raw: Mapping[str, object]) -> DcNetwork:
    """Strict schema for an offline, sanitized topology and 24h bus loads.

    Never guess PMSS internal schema or infer a generator's node from its name.
    """
    if not isinstance(raw, Mapping):
        raise ValueError("DC network document must be an object")
    expected = {
        "buses", "lines", "unitBus", "hourlyDemandMw", "slackBus", "baseMva",
        "topologySource", "demandSource",
    }
    if set(raw) != expected:
        raise ValueError(f"DC network schema keys must be exactly {sorted(expected)}")
    lines = raw["lines"]
    if not isinstance(lines, list) or any(not isinstance(x, Mapping) for x in lines):
        raise ValueError("lines must be an array of line objects")
    model_lines = []
    for line in lines:
        fields = {"lineId", "fromBus", "toBus", "reactancePu", "limitMw"}
        if set(line) != fields:
            raise ValueError("Each line needs verified endpoint, reactance and limit fields")
        model_lines.append(
            DcLine(
                str(line["lineId"]), str(line["fromBus"]), str(line["toBus"]),
                float(line["reactancePu"]), float(line["limitMw"]),
            )
        )
    buses = raw["buses"]
    unit_bus = raw["unitBus"]
    hourly = raw["hourlyDemandMw"]
    if not isinstance(buses, list) or any(not isinstance(b, str) for b in buses):
        raise ValueError("buses must be a list of IDs")
    if (
        not isinstance(unit_bus, dict) or not isinstance(hourly, dict)
        or any(not isinstance(v, str) for v in unit_bus.values())
        or any(not isinstance(v, list) for v in hourly.values())
    ):
        raise ValueError("Invalid generator-bus mapping or hourly loads")
    return DcNetwork(
        buses=tuple(buses),
        lines=tuple(model_lines),
        unit_bus=dict(unit_bus),
        hourly_demand_mw={
            bus: tuple(float(v) for v in series) for bus, series in hourly.items()
        },
        slack_bus=str(raw["slackBus"]),
        base_mva=float(raw["baseMva"]),
        topology_source=str(raw["topologySource"]),
        demand_source=str(raw["demandSource"]),
    )
