"""Synthetic KCL and PMSS-result alignment tests for historical-only audit."""
from types import SimpleNamespace

import pytest

from powerbid.network_dispatch import network_from_dict
from powerbid.network_historical_audit import audit_pmss_historical_grid


def _network():
    return network_from_dict({
        "buses": ["A", "B"],
        "lines": [{
            "lineId": "LINE", "fromBus": "A", "toBus": "B",
            "reactancePu": 0.1, "limitMw": 50.0,
        }],
        "unitBus": {"G1": "A", "G2": "B"},
        "hourlyDemandMw": {"A": [0.0]*24, "B": [180.0]*24},
        "slackBus": "A", "baseMva": 1.0,
        "topologySource": "synthetic two bus graph",
        "demandSource": "synthetic historical load",
    })


def _results():
    def row(ident, field, value):
        return {
            "elementId": ident, "marketTypeAtom": "DA",
            field: {"datas": [value]*24},
        }
    return {
        "marketTypeAtom": "DA", "periodNum": 24,
        "unitResults": [
            row("G1", "power", 50),
            row("G2", "power", 130),
        ],
        "nodalPrices": [
            row("A", "powerFlow", 10),
            row("B", "powerFlow", 50),
        ],
        "branchFlows": [row("LINE", "powerFlow", 50)],
    }


def _modeled():
    return tuple(SimpleNamespace(
        period=i,
        dispatched_mw=50,
        nodal_prices={"A": 10.0, "B": 50.0},
        branch_flows_mw={"LINE": 50.0},
    ) for i in range(1, 25))


def test_historical_kcl_and_model_alignment_are_explicit():
    report = audit_pmss_historical_grid(
        _network(), _results(), case_date="synthetic-day",
        modeled_hours=_modeled(), target_unit_id="G1",
    )
    assert report.balanced_hour_count == 24
    assert report.observed_missing_hours == 0
    assert report.generation_load_mae_mw == pytest.approx(0.0)
    assert report.bus_balance_mae_mw == pytest.approx(0.0)
    assert report.reverse_flow_bus_balance_mae_mw == pytest.approx(100.0)
    assert report.modeled_nodal_price_mae == 0
    assert report.modeled_abs_flow_mae_mw == 0
    assert report.modeled_target_dispatch_mae_mw == 0
    assert report.observed_line_over_nameplate_hours == 0
    assert report.total_day_ahead_energy_mwh == 4320.0
    assert "NOT held-out accuracy" in report.disclaimer


def test_historical_kcl_preserves_missing_hours_and_does_not_zero_fill():
    results = _results()
    results["branchFlows"][0]["powerFlow"]["datas"][2] = None
    report = audit_pmss_historical_grid(_network(), results, case_date="synthetic")
    assert report.balanced_hour_count == 23
    assert report.observed_missing_hours == 1
    assert report.hours[2].observed_bus_balance_mae_mw is None
    assert report.hours[2].complete_observation is False
    assert report.hours[2].observed_line_count == 0
    assert report.hours[3].complete_observation is True


def test_historical_kcl_flags_observed_branch_above_nameplate_without_relabeling():
    results = _results()
    results["branchFlows"][0]["powerFlow"]["datas"][5] = 51
    report = audit_pmss_historical_grid(_network(), results, case_date="synthetic")
    assert report.observed_line_over_nameplate_hours == 1
    assert report.hours[5].observed_line_over_nameplate_count == 1
    assert report.hours[5].observed_bus_balance_mae_mw == pytest.approx(1.0)
    assert report.worst_bus_balance[0].mae > 0


def test_historical_kcl_rejects_duplicate_id_non_da_and_wrong_history():
    result = _results()
    result["unitResults"][1]["elementId"] = "G1"
    with pytest.raises(ValueError, match="duplicate|differ|ID"):
        audit_pmss_historical_grid(_network(), result, case_date="synthetic")
    result = _results()
    result["marketTypeAtom"] = "RT"
    with pytest.raises(ValueError, match="day-ahead"):
        audit_pmss_historical_grid(_network(), result, case_date="synthetic")
    result = _results()
    with pytest.raises(ValueError, match="target"):
        audit_pmss_historical_grid(
            _network(), result, case_date="synthetic",
            modeled_hours=_modeled(), target_unit_id="missing",
        )
    with pytest.raises(ValueError, match="date"):
        audit_pmss_historical_grid(_network(), result, case_date=" ")


def test_model_comparison_never_accepts_disordered_hour_data():
    wrong = list(_modeled())
    wrong[0] = SimpleNamespace(
        period=2, dispatched_mw=50,
        nodal_prices={"A": 10, "B": 50},
        branch_flows_mw={"LINE": 50},
    )
    with pytest.raises(ValueError, match="ordered"):
        audit_pmss_historical_grid(
            _network(), _results(), case_date="synthetic",
            modeled_hours=wrong, target_unit_id="G1",
        )
