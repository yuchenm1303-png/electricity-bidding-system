"""Fixed-observed-injection DC flow replay: diagnose error sources separately."""
from dataclasses import replace

import pytest

from powerbid.fixed_injection_diagnostics import replay_observed_injections
from powerbid.network_dispatch import DcLine, DcNetwork


def _network():
    return DcNetwork(
        buses=("A", "B"),
        lines=(DcLine("AB", "A", "B", 0.1, 50),),
        unit_bus={"G1": "A", "G2": "B"},
        hourly_demand_mw={"A": (0.0,) * 24, "B": (180.0,) * 24},
        slack_bus="A",
        base_mva=100,
        topology_source="verified synthetic test topology",
        demand_source="synthetic sample",
    )


def _history():
    return {
        "marketTypeAtom": "DA",
        "periodNum": 24,
        "unitResults": [
            {"elementId": "G1", "marketTypeAtom": "DA", "power": {"datas": [50] * 24}},
            {"elementId": "G2", "marketTypeAtom": "DA", "power": {"datas": [130] * 24}},
        ],
        "branchFlows": [
            {"elementId": "AB", "marketTypeAtom": "DA", "powerFlow": {"datas": [50] * 24}},
        ],
    }


def test_fixed_injection_reproduces_zero_error_for_two_bus_line():
    result = replay_observed_injections(
        _network(), _history(), case_date="2025-09-01"
    )
    assert result.modeled_hours == 24
    assert result.missing_injection_hours == 0
    assert result.unbalanced_injection_hours == 0
    assert result.observed_line_points == 24
    assert result.flow_magnitude_mae_mw == pytest.approx(0, abs=1e-7)
    assert result.flow_signed_mae_mw == pytest.approx(0, abs=1e-7)
    assert result.flow_reversed_mae_mw == pytest.approx(100)
    assert result.modeled_line_over_limit_count == 0
    assert all(row.status == "MODELED" for row in result.hours)


def test_reverse_pmss_flow_convention_can_be_detected_without_guessing():
    sample = _history()
    sample["branchFlows"][0]["powerFlow"]["datas"] = [-50] * 24
    r = replay_observed_injections(_network(), sample, case_date="2025-09-01")
    assert r.flow_magnitude_mae_mw == pytest.approx(0, abs=1e-7)
    assert r.flow_signed_mae_mw == pytest.approx(100)
    assert r.flow_reversed_mae_mw == pytest.approx(0, abs=1e-7)


def test_missing_dispatch_skips_hour_without_inserting_zero_or_slack():
    sample = _history()
    sample["unitResults"][0]["power"]["datas"][4] = None
    report = replay_observed_injections(
        _network(), sample, case_date="2025-09-01"
    )
    assert report.modeled_hours == 23
    assert report.missing_injection_hours == 1
    assert report.observed_line_points == 23
    assert report.hours[4].status == "MISSING_GENERATION"
    assert report.hours[4].flow_magnitude_mae_mw is None


def test_generation_load_mismatch_skips_hour_and_reports_reason():
    sample = _history()
    sample["unitResults"][1]["power"]["datas"][1] = 100
    report = replay_observed_injections(
        _network(), sample, case_date="2025-09-01"
    )
    assert report.unbalanced_injection_hours == 1
    assert report.modeled_hours == 23
    assert report.hours[1].status == "GENERATION_LOAD_IMBALANCE"
    assert report.hours[1].generation_load_residual_mw == pytest.approx(-30)
    assert report.hours[1].compared_lines == 0


def test_missing_branch_series_reduces_coverage_without_zero_fill():
    sample = _history()
    sample["branchFlows"][0]["powerFlow"]["datas"][7] = None
    report = replay_observed_injections(
        _network(), sample, case_date="2025-09-01"
    )
    assert report.modeled_hours == 24
    assert report.observed_line_points == 23
    assert report.per_line[0].observed_points == 23
    assert report.hours[7].compared_lines == 0
    assert report.hours[7].flow_magnitude_mae_mw is None


def test_dc_predicted_line_over_limit_is_reported_not_clipped():
    small_limit = replace(
        _network(), lines=(DcLine("AB", "A", "B", 0.1, 20),)
    )
    report = replay_observed_injections(
        small_limit, _history(), case_date="2025-09-01"
    )
    assert report.modeled_line_over_limit_count == 24
    assert report.per_line[0].modeled_limit_exceed_count == 24
    assert report.flow_magnitude_mae_mw == pytest.approx(0)


def test_three_bus_loop_has_physically_consistent_split():
    # Triangle: A->B and A->C->B (all x=1) => direct flow 2/3,
    # two-series path 1/3 for 30 MW at A supplying B.
    net = DcNetwork(
        buses=("A", "B", "C"),
        lines=(
            DcLine("AB", "A", "B", 1, 100),
            DcLine("AC", "A", "C", 1, 100),
            DcLine("CB", "C", "B", 1, 100),
        ),
        unit_bus={"G": "A"},
        hourly_demand_mw={
            "A": (0.0,) * 24, "B": (30.0,) * 24, "C": (0.0,) * 24
        },
        slack_bus="A", base_mva=100,
        topology_source="synthetic triangle", demand_source="synthetic",
    )
    observed = {
        "marketTypeAtom": "DA", "periodNum": 24,
        "unitResults": [
            {"unit_id": "G", "market_type": "DA", "accepted_mw": [30] * 24},
        ],
        "branchFlows": [
            {"element_id": x, "market_type": "DA", "flow_mw": [f] * 24}
            for x, f in [("AB", 20), ("AC", 10), ("CB", 10)]
        ],
    }
    report = replay_observed_injections(net, observed, case_date="2025-09-01")
    assert report.flow_magnitude_mae_mw == pytest.approx(0, abs=1e-7)
    assert report.modeled_hours == 24


def test_reject_invalid_history_duplicate_ids_wrong_market_or_mismatched_date():
    sample = _history()
    sample["unitResults"][1]["elementId"] = "G1"
    with pytest.raises(ValueError, match="Duplicate|IDs"):
        replay_observed_injections(_network(), sample, case_date="2025-09-01")
    sample = _history()
    sample["marketTypeAtom"] = "RT"
    with pytest.raises(ValueError, match="DA"):
        replay_observed_injections(_network(), sample, case_date="2025-09-01")
    with pytest.raises(ValueError, match="ISO"):
        replay_observed_injections(_network(), _history(), case_date="tomorrow")


def test_zero_or_non_finite_balance_tolerance_is_rejected():
    with pytest.raises(ValueError, match="tolerance"):
        replay_observed_injections(
            _network(), _history(), case_date="2025-09-01",
            balance_tolerance_mw=float("nan"),
        )
