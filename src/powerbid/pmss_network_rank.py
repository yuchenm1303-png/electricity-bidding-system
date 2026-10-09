"""Price-rule-safe DC-network strategy *research* ranking using existing solvers.

Only original 24h PMSS data, current 5-band market rules and a verified
network are accepted. The historical original bid is compared for context but
NEVER returned as an eligible new bid, particularly when old saved bids
conflict with current market limits.

The three equally weighted peer-price perturbations are a synthetic
sensitivity test, NOT a probabilistic forecast. This module never contacts
PMSS, submits a bid, or claims the candidate has been market-cleared there.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from powerbid.network_dispatch import DcNetwork
from powerbid.network_strategy import (
    NetworkBidResult,
    compare_network_policies,
    verify_network_inputs,
)
from powerbid.pmss_bid_rule_safety import (
    audit_saved_bid_price_limits,
    validate_new_curve,
)
from powerbid.pmss_integration import PMSSSnapshot, curve_for_period
from powerbid.strategy_lab import BidPolicy, DemandStress, generate_policy_plan


@dataclass(frozen=True, slots=True)
class RankedCurve:
    name: str
    score: float
    expected_margin: float
    downside_margin: float
    worst_margin: float
    expected_accepted_mwh: float
    price_blocks: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True, slots=True)
class NetworkBidResearch:
    target_unit_id: str
    baseline_score: float
    baseline_expected_margin: float
    baseline_rule_compatible: bool
    eligible_candidates: tuple[RankedCurve, ...]
    best_candidate: RankedCurve
    modeled_better_than_baseline: bool | None
    price_floor: float | None
    price_ceiling: float | None
    historical_units_outside_current_rule: int
    synthetic_scenarios: tuple[str, ...]
    historical_evidence_days: int = 0
    validated_for_real_bidding: bool = False
    confidence_status: str = "RESEARCH_ONLY_NOT_OUT_OF_SAMPLE_VALIDATED"
    assumption: str = (
        "Local lossless DC model, independent hourly optimization, fixed "
        "historical peer bids; peer-price stresses are synthetic, not "
        "probability forecasts. No startup/ramp/AC losses or PMSS repricing."
    )


def _summarize(result: NetworkBidResult) -> RankedCurve:
    blocks = curve_for_period(result.periods, 1)
    return RankedCurve(
        name=result.name,
        score=result.score,
        expected_margin=result.expected_margin,
        downside_margin=result.downside_margin,
        worst_margin=result.worst_margin,
        expected_accepted_mwh=result.expected_accepted_mwh,
        price_blocks=tuple(
            (block.start_power, block.end_power, block.price) for block in blocks
        ),
    )


def rank_network_bid_strategies(
    snapshot: PMSSSnapshot,
    network: DcNetwork,
    target_unit_id: str,
    *,
    risk_aversion: float = 0.5,
    peer_price_deviation: float = 0.05,
) -> NetworkBidResearch:
    """Rank four bounded markup policies *inside* existing 24h DC network.

    Baseline is evaluated for historical diagnostics even if its original
    saved prices conflict with newer rules. If any historical generator
    exceeds the current market bounds, comparing scores is non-actionable
    because peers are not normalized to today's hypothetical legality.
    """
    verify_network_inputs(snapshot, network, target_unit_id)
    if snapshot.limits.market_type != "DA" or snapshot.period_num != 24:
        raise ValueError("Only 24h DA research snapshots are supported")
    if not isinstance(risk_aversion, (int, float)) or isinstance(risk_aversion, bool):
        raise ValueError("Risk aversion must be numeric")
    if not isfinite(risk_aversion) or not 0 <= risk_aversion <= 1:
        raise ValueError("Risk aversion must be in [0, 1]")
    if not isinstance(peer_price_deviation, (int, float)) or isinstance(peer_price_deviation, bool):
        raise ValueError("Peer deviation must be numeric")
    if not isfinite(peer_price_deviation) or not 0 <= peer_price_deviation <= 0.15:
        raise ValueError("Peer-price sensitivity outside 0..15%")
    if len(network.buses) > 60 or len(network.lines) > 90 or len(snapshot.units) > 30:
        raise ValueError("Online risk comparison exceeds bounded grid size")
    if len(snapshot.bids[target_unit_id]) == 0:
        raise ValueError("No original target bidding plan")

    # All candidate curves honor today's 0-1000 (or other snapshotted)
    # market rule. Avoid silently clipping an out-of-range price: changing
    # the tariff is a different candidate and must be labeled as such.
    proposals = []
    for markup in (0.0, 20.0, 50.0, 100.0):
        policy = BidPolicy(name=f"当前规则内加价 {markup:g}", markup=markup)
        plan = generate_policy_plan(snapshot, target_unit_id, policy)
        try:
            for period in plan:
                validate_new_curve(snapshot, target_unit_id, period.segments)
        except ValueError:
            continue
        proposals.append(policy)
    if not proposals:
        raise ValueError("No price-rule-compliant five-segment policies available")

    scenarios = tuple(
        DemandStress(
            name=f"peer_bid_x{factor:.3f}",
            demand_factor=1.0,
            peer_price_factor=factor,
            probability=1.0,
        )
        for factor in (
            1.0 - peer_price_deviation,
            1.0,
            1.0 + peer_price_deviation,
        )
    )
    compared = compare_network_policies(
        snapshot, network, target_unit_id,
        policies=proposals,
        scenarios=scenarios,
        risk_aversion=risk_aversion,
        tail_fraction=1 / 3,
    )
    # Never confuse the old recorded bid with a new proposed curve.
    legal_candidates = tuple(
        _summarize(item)
        for item in compared.ranked
        if item.name != compared.baseline.name
    )
    if not legal_candidates:
        raise ValueError("All new curves are identical to baseline; no distinct legal candidate")
    audit = audit_saved_bid_price_limits(snapshot)
    baseline_compatible = audit.original_units_outside_current_range == 0
    best = legal_candidates[0]
    return NetworkBidResearch(
        target_unit_id=target_unit_id,
        baseline_score=compared.baseline.score,
        baseline_expected_margin=compared.baseline.expected_margin,
        baseline_rule_compatible=baseline_compatible,
        eligible_candidates=legal_candidates,
        best_candidate=best,
        modeled_better_than_baseline=(
            best.score > compared.baseline.score + 1e-7
            if baseline_compatible else None
        ),
        price_floor=snapshot.limits.price_floor,
        price_ceiling=snapshot.limits.price_ceiling,
        historical_units_outside_current_rule=audit.original_units_outside_current_range,
        synthetic_scenarios=tuple(v.name for v in scenarios),
    )
