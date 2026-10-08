"""Observed PMSS feedback remains read-only and non-predictive."""
from dataclasses import replace

import pytest

from powerbid.observed_feedback import audit_observed_dispatch, observed_unit_day
from test_physical_strategy_audit import _physical


def _result():
    return {
        "marketTypeAtom": "DA",
        "periodNum": 24,
        "unitResults": [
            {
                "unit_id": "G1",
                "market_type": "DA",
                "accepted_mw": [100.0] * 24,
                "clearing_prices": [350.0] * 24,
                "income": [0.2] * 24,
            },
            {
                "unit_id": "G2",
                "market_type": "DA",
                "accepted_mw": [10.0] * 24,
                "clearing_prices": [100.0] * 24,
                "income": [100.0] * 24,
            },
        ],
    }


def test_observed_income_keeps_platform_reported_scale():
    obs = observed_unit_day(_result(), unit_id="G1")
    assert obs.observed_energy_mwh == pytest.approx(2400.0)
    assert obs.observed_income_raw == pytest.approx(4.8)
    assert obs.reported_income == pytest.approx([0.2] * 24)
    assert obs.nonmissing_income_hours == 24
    assert audit_observed_dispatch(obs, _physical()).feasible


def test_incorrect_unit_or_market_selection_fails_closed():
    with pytest.raises(ValueError, match="exactly one"):
        observed_unit_day(_result(), unit_id="missing")
    with pytest.raises(ValueError, match="market_type"):
        observed_unit_day(_result(), unit_id="G1", market_type="RT")
    with pytest.raises(ValueError, match="unit IDs"):
        audit_observed_dispatch(
            observed_unit_day(_result(), unit_id="G1"), _physical(unit_id="G2")
        )


def test_missing_observed_mw_not_treated_as_zero_or_feasible():
    result = _result()
    result["unitResults"][0]["accepted_mw"][12] = None
    obs = observed_unit_day(result, unit_id="G1")
    assert obs.nonmissing_power_hours == 23
    with pytest.raises(ValueError, match="unknown"):
        audit_observed_dispatch(obs, _physical())


def test_duplicate_and_invalid_market_observations_rejected():
    result = _result()
    result["unitResults"].append(result["unitResults"][0])
    with pytest.raises(ValueError, match="exactly one"):
        observed_unit_day(result, unit_id="G1")
    result = _result()
    result["unitResults"][0]["accepted_mw"] = [-1.0] * 24
    with pytest.raises(ValueError, match="negative"):
        observed_unit_day(result, unit_id="G1")


def test_partial_income_is_marked_incomplete_not_extrapolated():
    result = _result()
    result["unitResults"][0]["income"][3] = None
    obs = observed_unit_day(result, unit_id="G1")
    assert obs.nonmissing_income_hours == 23
    assert obs.observed_income_raw == pytest.approx(4.6)
