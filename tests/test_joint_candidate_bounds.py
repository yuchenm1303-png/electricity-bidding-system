"""24-hour integrated optimal-cost MWh bounds must respect inter-hour physics."""
from dataclasses import replace

import pytest
from test_joint_market import _model
from test_pmss_joint_research import fixtures

from powerbid.joint_candidate_bounds import assess_joint_candidate_mwh_envelope
from powerbid.joint_market import JointMwhExtreme, joint_clear_day
from powerbid.network_dispatch import DcNetwork
from powerbid.pmss_integration import BidSegment, PeriodBid


def test_joint_mwh_extreme_original_market_physics_are_preserved():
    snap, network, specs = _model()
    plan = (PeriodBid(1, 24, (BidSegment(0, 100, 60),)),)
    extreme_min = joint_clear_day(
        snap, network, specs, "G1",
        candidate_plan=plan, target_mwh_extreme="minimum",
    )
    extreme_max = joint_clear_day(
        snap, network, specs, "G1",
        candidate_plan=plan, target_mwh_extreme="maximum",
    )
    assert isinstance(extreme_min, JointMwhExtreme)
    assert isinstance(extreme_max, JointMwhExtreme)
    assert len(extreme_min.target_dispatch_24h) == 24
    assert extreme_min.target_accepted_mwh == pytest.approx(30*24, abs=0.01)
    assert extreme_max.target_accepted_mwh == pytest.approx(30*24, abs=0.01)
    assert extreme_min.primary_optimum_cost == pytest.approx(
        extreme_max.primary_optimum_cost, abs=0.001
    )
    assert extreme_max.extreme_total_cost <= (
        extreme_max.primary_optimum_cost +
        extreme_max.allowed_cost_increase + 1e-4
    )
    assert all(extreme_min.target_online_24h)
    assert "no LMPs" in extreme_min.model_label


def test_interhour_ramp_can_close_an_independent_hourly_mw_interval():
    # With identical bids, the hourly DC model could freely dispatch G1
    # from 0..100 MW. Its 24h MILP has an explicit verified synthetic G1
    # zero upward ramp from initial 0 and min up 24 hours, so G1 cannot
    # increase energy over the entire horizon.
    snap, _, specs = _model()
    snap = replace(snap, demand_forecast_mw=(100.0,)*24)
    network = DcNetwork(
        buses=("A",), lines=(), unit_bus={"G1":"A", "G2":"A"},
        hourly_demand_mw={"A":(100.0,)*24}, slack_bus="A",
        base_mva=100, topology_source="synthetic single bus",
        demand_source=snap.forecast_source,
    )
    spec1 = replace(
        specs["G1"], min_mw=0, ramp_up_mw=0, ramp_down_mw=0,
        min_up_hours=24, initial_on=True, initial_mw=0,
        initial_state_hours=1, shutdown_ramp_mw=100,
    )
    spec2 = replace(specs["G2"], initial_mw=100, max_mw=150)
    specs = {"G1":spec1,"G2":spec2}
    curve = (PeriodBid(1,24,(BidSegment(0,100,90),)),)
    lower = joint_clear_day(
        snap,network,specs,"G1",
        candidate_plan=curve,
        terminal_mode="carryover",
        target_mwh_extreme="minimum",
    )
    upper = joint_clear_day(
        snap,network,specs,"G1",
        candidate_plan=curve,
        terminal_mode="carryover",
        target_mwh_extreme="maximum",
    )
    assert isinstance(lower, JointMwhExtreme)
    assert isinstance(upper, JointMwhExtreme)
    assert lower.target_accepted_mwh == pytest.approx(0,abs=0.002)
    assert upper.target_accepted_mwh == pytest.approx(0,abs=0.002)


def test_envelope_refuses_missing_incomplete_or_unverified_technical_data():
    snap, network, records = fixtures()
    bid=(BidSegment(0,100,60),)
    with pytest.raises(ValueError, match="must be explicitly"):
        assess_joint_candidate_mwh_envelope(
            snap,network,records,"G1",bid,
            technical_source="user_supplied_unverified",
            technical_source_description="unverified",
        )
    with pytest.raises(ValueError, match="BLOCKED"):
        assess_joint_candidate_mwh_envelope(
            snap,network,{}, "G1",bid,
            technical_source="course_verified_by_user",
            technical_source_description="no data",
        )
    with pytest.raises(ValueError, match="BLOCKED"):
        incomplete={k:dict(v) for k,v in records.items()}
        incomplete["G1"].pop("initial_on")
        assess_joint_candidate_mwh_envelope(
            snap,network,incomplete,"G1",bid,
            technical_source="synthetic",
            technical_source_description="synthetic",
        )


def test_joint_bound_synthetic_output_is_not_real_pmss_forecast():
    snap, network, records = fixtures()
    result=assess_joint_candidate_mwh_envelope(
        snap,network,records,"G1",(BidSegment(0,100,60),),
        technical_source="synthetic",
        technical_source_description="Bundled two-unit synthetic data",
    )
    assert len(result.minimum_24h_dispatch_mw)==24
    assert len(result.maximum_24h_dispatch_mw)==24
    assert result.minimum_accepted_mwh<=result.maximum_accepted_mwh+1e-3
    assert result.minimum_accepted_mwh==pytest.approx(720,abs=0.05)
    assert result.maximum_accepted_mwh==pytest.approx(720,abs=0.05)
    assert not result.readiness.independently_verified
    assert result.safe_for_live_submission is False
    assert result.independent_pmss_technical_verification is False
    assert result.counterfactual_pmss_verified is False
    assert result.uses_historical_outcomes_as_forecast is False


def test_explicit_source_and_legal_new_bid_are_mandatory():
    snap, network, records = fixtures()
    args=dict(
        snapshot=snap,network=network,technical=records,
        target_unit_id="G1",new_segments=(BidSegment(0,100,60),),
        technical_source="synthetic", technical_source_description="synthetic",
    )
    with pytest.raises(ValueError, match="price"):
        assess_joint_candidate_mwh_envelope(
            **(args | {"new_segments":(BidSegment(0,100,1001),)})
        )
    with pytest.raises(ValueError, match="source"):
        assess_joint_candidate_mwh_envelope(
            **(args | {"technical_source_description":" "})
        )
    with pytest.raises(ValueError, match="terminal"):
        assess_joint_candidate_mwh_envelope(
            **(args | {"terminal_mode":"unknown"})
        )
    with pytest.raises(ValueError, match="tolerance"):
        joint_clear_day(
            snap,network,{key:replace(_model()[2][key]) for key in ("G1","G2")},
            "G1",target_mwh_extreme="minimum",
            extreme_cost_tolerance_abs=-1,
        )
