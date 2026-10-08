"""End-to-end risk-aware bidding under integrated 24h network and commitment."""
from dataclasses import replace

import pytest
from test_joint_market import _model

from powerbid.joint_market import JointInfeasibleError
from powerbid.joint_strategy import compare_joint_bids, evaluate_joint_bid
from powerbid.pmss_integration import BidSegment, PeriodBid
from powerbid.strategy_lab import BidPolicy, DemandStress


def test_joint_strategy_evaluates_real_dispatch_not_exogenous_price():
    snap, network, spec = _model()
    scenarios = (
        DemandStress("neutral", demand_factor=1, peer_price_factor=1, probability=3),
        DemandStress("peer higher", demand_factor=1, peer_price_factor=1.1, probability=1),
    )
    baseline = evaluate_joint_bid(
        snap, network, spec, "G1", "original",
        snap.bids["G1"], scenarios,
    )
    assert baseline.scenarios[0].probability == pytest.approx(0.75)
    assert baseline.scenarios[1].probability == pytest.approx(0.25)
    assert baseline.scenarios[0].market.hours[0].nodal_prices["A"] == pytest.approx(60)
    assert baseline.expected_accepted_mwh == pytest.approx(720)
    assert baseline.expected_net_profit == pytest.approx(24 * 30 * (60-50))
    assert baseline.risk_score == pytest.approx(baseline.expected_net_profit)
    assert "NOT observed PMSS" in baseline.model_label


def test_joint_bid_price_changes_nodal_dispatch_and_profit():
    snap, network, spec = _model()
    normal = (DemandStress("neutral"),)
    baseline = evaluate_joint_bid(
        snap, network, spec, "G1", "old", snap.bids["G1"], normal
    )
    alternative = evaluate_joint_bid(
        snap, network, spec, "G1", "new",
        (PeriodBid(1, 24, (BidSegment(0, 100, 95),)),),
        normal,
    )
    assert alternative.scenarios[0].market.hours[0].accepted_by_unit["G1"] < 30
    assert alternative.expected_accepted_mwh < baseline.expected_accepted_mwh


def test_joint_candidate_ranking_includes_history_and_preserves_inputs():
    snap, network, spec = _model()
    result = compare_joint_bids(
        snap, network, spec, "G1",
        policies=(
            BidPolicy("cost"),
            BidPolicy("fixed markup", markup=20),
            BidPolicy("steps", markup=5, slope=10),
        ),
    )
    assert 2 <= result.evaluated <= 4
    assert result.recommended in result.ranked
    assert result.ranked[0].risk_score >= result.ranked[-1].risk_score
    assert result.baseline.name.startswith("PMSS 已申报")
    assert result.baseline.periods == snap.bids["G1"]
    assert snap.bids["G1"][0].segments[0].price == 60


def test_infeasible_stress_is_not_masked_as_zero_profit():
    snap, network, spec = _model()
    with pytest.raises(JointInfeasibleError):
        compare_joint_bids(
            snap, network, spec, "G1",
            policies=(BidPolicy("cost"),),
            scenarios=(DemandStress("large load", demand_factor=1.2),),
        )


def test_no_surrogate_proof_of_real_pmss_profit():
    snap, network, spec = _model()
    r = compare_joint_bids(
        snap, network, spec, "G1",
        policies=(BidPolicy("cost"),),
    )
    assert all(
        result.model_label.endswith("NOT observed PMSS profit")
        for result in r.ranked
    )


def test_compare_rejects_oversized_scenario_or_policy_budget():
    snap, network, spec = _model()
    with pytest.raises(ValueError, match="three"):
        compare_joint_bids(
            snap, network, spec, "G1", policies=(BidPolicy("cost"),),
            scenarios=tuple(DemandStress(f"x{i}") for i in range(4)),
        )
    with pytest.raises(ValueError, match="one to six"):
        compare_joint_bids(
            snap, network, spec, "G1",
            policies=tuple(BidPolicy(f"p{i}") for i in range(7)),
        )


def test_g1_must_be_known_with_matching_physical_record():
    snap, network, spec = _model()
    spec_bad = dict(spec)
    spec_bad["G1"] = replace(spec_bad["G1"], unit_id="MISMATCH")
    with pytest.raises(ValueError, match="does not match"):
        compare_joint_bids(
            snap, network, spec_bad, "G1", policies=(BidPolicy("cost"),)
        )
