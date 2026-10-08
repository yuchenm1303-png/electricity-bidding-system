from math import isclose

import pytest

from powerbid.pmss_diagnostics import (
    analyze_historical_network,
    compare_baseline_to_pmss,
    series24,
)
from powerbid.pmss_integration import BidSegment
from powerbid.pmss_strategy import CurveEvaluation, HourlyTrial


def fake_results(normalized=False):
    def record(ident, **items):
        if normalized:
            return {"element_id": ident, "market_type": "DA", **items}
        return {"elementId": ident, "marketTypeAtom": "DA", **items}

    if normalized:
        nodes = [record("n1", lmp=[100.0] * 24), record("n2", lmp=[250.0] * 24)]
        branches = [record(
            "line", flow_mw=[-50.0] * 24,
            shadow_price=[0.0, 10.0] + [None] * 22,
        )]
        units = [record("G30", unit_id="G30", accepted_mw=[20.0] * 24,
                        clearing_prices=[140.0] * 24)]
    else:
        nodes = [record("n1", powerFlow={"datas": [100.0] * 24}),
                 record("n2", powerFlow={"datas": [250.0] * 24})]
        branches = [record(
            "line", powerFlow={"datas": [-50.0] * 24},
            shadowPrice={"datas": [0.0, 10.0] + [None] * 22},
        )]
        units = [record("G30", power={"datas": [20.0] * 24},
                        price={"datas": [140.0] * 24})]
    return {
        "periodNum": 24,
        "marketTypeAtom": "DA",
        "unitResults": units,
        "nodalPrices": nodes,
        "branchFlows": branches,
    }


def baseline():
    hours = [
        HourlyTrial(
            period=i, demand_mw=300,
            clearing_price=120.0, target_accepted_mw=10.0,
            target_profit=500.0, feasible=True,
        )
        for i in range(1, 25)
    ]
    return CurveEvaluation(
        segments=(BidSegment(0.0, 30.0, 100.0),),
        total_profit=12000.0, worst_hour_profit=500.0,
        total_accepted_mwh=240.0, hours=tuple(hours),
    )


@pytest.mark.parametrize("normalized", [False, True])
def test_network_diagnostics_do_not_confuse_lmp_with_line_flow(normalized):
    output = analyze_historical_network(fake_results(normalized))
    assert output.node_count == 2
    assert output.branch_count == 1
    assert output.price_coverage_points == 48
    assert output.flow_coverage_points == 24
    assert output.hourly[0].mean_lmp == 175.0
    assert output.hourly[0].lmp_spread == 150.0
    assert output.hourly[0].nonzero_shadow_branches == 0
    assert output.hourly[1].nonzero_shadow_branches == 1
    assert output.hourly[1].max_abs_flow_mw == 50.0
    assert output.most_shadowed[0].hours_nonzero_shadow == 1
    assert output.most_shadowed[0].peak_abs_shadow == 10.0
    assert "historical" in output.label


@pytest.mark.parametrize("normalized", [False, True])
def test_baseline_comparison_not_candidate_counterfactual(normalized):
    compared = compare_baseline_to_pmss(
        target_unit_id="G30", baseline=baseline(), results=fake_results(normalized),
    )
    assert compared.observed_power_points == 24
    assert isclose(compared.power_mae_mw, 10.0)
    assert isclose(compared.power_rmse_mw, 10.0)
    assert compared.hours[0].observed_unit_price == 140
    assert compared.hours[0].surrogate_uniform_price == 120


def test_partial_null_data_coverage_is_not_mislabeled_as_zero():
    data = fake_results()
    data["nodalPrices"][0]["powerFlow"]["datas"][0] = None
    data["unitResults"][0]["power"]["datas"][0] = None
    network = analyze_historical_network(data)
    assert network.hourly[0].nodes_with_price == 1
    comparison = compare_baseline_to_pmss(
        target_unit_id="G30", baseline=baseline(), results=data,
    )
    assert comparison.observed_power_points == 23
    assert comparison.hours[0].absolute_error_mw is None


def test_rejects_incorrect_market_and_duplicate_nodes():
    data = fake_results()
    data["nodalPrices"].append(data["nodalPrices"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        analyze_historical_network(data)
    data = fake_results()
    data["branchFlows"][0]["marketTypeAtom"] = "RT"
    with pytest.raises(ValueError, match="non-DA"):
        analyze_historical_network(data)
    data = fake_results()
    data["marketTypeAtom"] = "RT"
    with pytest.raises(ValueError, match="DA"):
        analyze_historical_network(data)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), True, {}, "bad"])
def test_corrupt_input_is_rejected(value):
    with pytest.raises(ValueError):
        series24({"powerFlow": [value] * 24}, "powerFlow")


def test_missing_target_or_hour_count_rejected():
    with pytest.raises(ValueError, match="not found"):
        compare_baseline_to_pmss(
            target_unit_id="unknown", baseline=baseline(), results=fake_results(),
        )
    with pytest.raises(ValueError, match="24-point"):
        series24({"powerFlow": [20]}, "powerFlow")
