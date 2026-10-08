"""Read-only PMSS historical feedback for joint DC+unit commitment research."""
from dataclasses import replace

import pytest
from test_joint_market import _model

from powerbid.joint_feedback import compare_joint_baseline_history
from powerbid.joint_strategy import compare_joint_bids
from powerbid.strategy_lab import BidPolicy, DemandStress


def _observations(baseline):
    hours = baseline.scenarios[0].market.hours
    return {
        "marketTypeAtom": "DA",
        "periodNum": 24,
        "unitResults": [
            {
                "unit_id": unit, "market_type": "DA",
                "accepted_mw": [h.accepted_by_unit[unit] for h in hours],
            }
            for unit in ("G1", "G2")
        ],
        "nodalPrices": [
            {
                "element_id": bus, "market_type": "DA",
                "lmp": [h.nodal_prices[bus] for h in hours],
            }
            for bus in ("A", "B")
        ],
        "branchFlows": [{
            "element_id": "LINE-AB", "market_type": "DA",
            "flow_mw": [-h.line_flows_mw["LINE-AB"] for h in hours],
        }],
    }


def test_joint_baseline_only_has_zero_error_for_same_synthetic_observations():
    snap, net, specs = _model()
    evaluated = compare_joint_bids(
        snap, net, specs, "G1",
        policies=(BidPolicy("cost"),),
        scenarios=(DemandStress("neutral"),),
    )
    actual = _observations(evaluated.baseline)
    output = compare_joint_baseline_history(snap, net, evaluated.baseline, "G1", actual)
    assert output.target_dispatch_mae_mw == pytest.approx(0)
    assert output.target_dispatch_rmse_mw == pytest.approx(0)
    assert output.all_unit_dispatch_mae_mw == pytest.approx(0)
    assert output.all_bus_lmp_mae == pytest.approx(0)
    assert output.line_flow_magnitude_mae_mw == pytest.approx(0)
    assert output.target_points == 24
    assert output.unit_points == 48
    assert output.node_points == 48
    assert output.line_points == 24


def test_joint_historical_feedback_is_not_a_counterfactual_strategy_score():
    snap, net, specs = _model()
    evaluated = compare_joint_bids(
        snap, net, specs, "G1",
        policies=(BidPolicy("cost"), BidPolicy("markup 20", markup=20)),
        scenarios=(DemandStress("neutral"),),
    )
    observed = _observations(evaluated.baseline)
    candidate = next(
        x for x in evaluated.ranked if x.name == "markup 20"
    )
    with pytest.raises(ValueError, match="exact original"):
        compare_joint_baseline_history(snap, net, candidate, "G1", observed)


def test_strict_identity_and_missing_hours_are_not_imputed():
    snap, net, specs = _model()
    evaluated = compare_joint_bids(
        snap, net, specs, "G1",
        policies=(BidPolicy("cost"),),
        scenarios=(DemandStress("neutral"),),
    )
    observed = _observations(evaluated.baseline)
    observed["unitResults"][0]["accepted_mw"][4] = None
    observed["nodalPrices"][0]["lmp"][3] = None
    result = compare_joint_baseline_history(snap, net, evaluated.baseline, "G1", observed)
    assert result.target_points == 23
    assert result.unit_points == 47
    assert result.node_points == 47

    observed["branchFlows"][0]["element_id"] = "UNKNOWN"
    with pytest.raises(ValueError, match="IDs do not match"):
        compare_joint_baseline_history(snap, net, evaluated.baseline, "G1", observed)


def test_non_neutral_case_must_not_calibrate_baseline():
    snap, net, specs = _model()
    evaluated = compare_joint_bids(
        snap, net, specs, "G1",
        policies=(BidPolicy("cost"),),
        scenarios=(DemandStress("stressed", peer_price_factor=1.1),),
    )
    with pytest.raises(ValueError, match="neutral"):
        compare_joint_baseline_history(
            snap, net, evaluated.baseline, "G1",
            _observations(evaluated.baseline),
        )
