"""Ex-post median price residual: not a usable unseen-hour pricing rule."""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest
from test_historical_validation import _fixture

from powerbid.historical_error_profile import anonymized_error_profile
from powerbid.historical_validation import (
    ValidationPolicy,
    judge_historical_model,
    validate_historical_day,
)
from powerbid.price_residual_shape import price_residual_shape


def test_common_signed_price_error_is_uniform_but_not_a_proven_price_cap():
    measured = price_residual_shape([50.0, 50.0, 50.0])
    assert measured.compared_nodes == 3
    assert measured.raw_mae == pytest.approx(50)
    assert measured.signed_median_shift == pytest.approx(50)
    assert measured.centered_mae == pytest.approx(0)
    assert measured.residual_range == pytest.approx(0)
    assert measured.uniform_shift_within_tolerance is True


def test_spatial_price_error_cannot_be_explained_by_a_single_shift():
    measured = price_residual_shape([0.0, -100.0])
    assert measured.raw_mae == pytest.approx(50)
    assert measured.signed_median_shift == pytest.approx(-50)
    assert measured.centered_mae == pytest.approx(50)
    assert measured.residual_range == pytest.approx(100)
    assert measured.uniform_shift_within_tolerance is False
    skew = price_residual_shape([20.0, 20.0, -50.0])
    assert skew.signed_median_shift == pytest.approx(20)
    assert skew.centered_mae == pytest.approx(70/3)
    assert skew.raw_mae == pytest.approx(30)


def test_single_observed_node_cannot_fabricate_zero_mae_spatial_shape():
    alone = price_residual_shape([-10])
    assert alone.compared_nodes == 1
    assert alone.raw_mae == pytest.approx(10)
    assert alone.centered_mae is None
    assert alone.signed_median_shift is None
    assert alone.residual_range is None
    assert alone.uniform_shift_within_tolerance is None
    empty = price_residual_shape([])
    assert empty.raw_mae is None
    assert empty.centered_mae is None


@pytest.mark.parametrize(("values", "tolerance"), [
    ([float("nan")], 1e-5), ([float("inf")], 1e-5),
    (["bad"], 1e-5), ([1], -1), ([1], float("inf")),
    ([1], True), ("not a sequence", 1e-5),
])
def test_invalid_or_nonfinite_residual_inputs_rejected(values, tolerance):
    with pytest.raises(ValueError):
        price_residual_shape(values, uniform_tolerance=tolerance)


def test_hourly_integrated_observed_common_shift_preserves_raw_error():
    case = _fixture()
    for row in case["results"]["nodalPrices"]:
        row["lmp"] = [v + 50 for v in row["lmp"]]
    day = validate_historical_day(case)
    assert day.nodal_price.mae == pytest.approx(50)
    h = day.hourly_profile[0]
    assert h.nodal_price_mae == pytest.approx(50)
    assert h.nodal_price_median_signed_residual == pytest.approx(-50)
    assert h.nodal_price_median_centered_mae == pytest.approx(0, abs=1e-8)
    assert h.nodal_price_residual_range == pytest.approx(0, abs=1e-8)
    assert h.nodal_price_compared_nodes_for_shape == 2
    assert h.nodal_price_uniform_shift_within_tolerance is True


def test_only_one_node_observed_preserves_missing_spatial_diagnostic():
    case = _fixture()
    case["results"]["nodalPrices"][1]["lmp"][0] = None
    case["results"]["nodalPrices"][0]["lmp"][0] += 100
    day = validate_historical_day(case)
    h = day.hourly_profile[0]
    assert h.nodal_price_compared_nodes_for_shape == 1
    assert h.nodal_price_mae == pytest.approx(100)
    assert h.nodal_price_median_centered_mae is None
    assert h.nodal_price_residual_range is None
    report = anonymized_error_profile(
        [day], judge_historical_model([day], ValidationPolicy(40, 50)),
        ValidationPolicy(40, 50),
    )
    shape = report["dates"][0]["priceResidualStructure"]
    assert shape["spatiallyComparableNodeHours"] == 46
    assert shape["hoursWithoutEnoughObservedNodes"] == 1
    assert shape["rawMaeOnSameEligibleNodes"] == pytest.approx(0)
    assert shape["bestExPostHourlyUniformShiftMae"] == pytest.approx(0)


def test_three_day_anonymized_price_shape_shows_common_vs_spatial_structure():
    cases = [
        _fixture("2025-09-01"),
        _fixture("2025-09-02"),
        _fixture("2025-09-03"),
    ]
    for row in cases[0]["results"]["nodalPrices"]:
        row["lmp"] = [v + 100 for v in row["lmp"]]
    for value in cases[1]["results"]["nodalPrices"][:1]:
        value["lmp"] = [v + 100 for v in value["lmp"]]
    days = [validate_historical_day(case) for case in cases]
    policy = ValidationPolicy(40, 120)
    report = anonymized_error_profile(
        days, judge_historical_model(days, policy), policy
    )
    common = report["dates"][0]["priceResidualStructure"]
    spread = report["dates"][1]["priceResidualStructure"]
    clean = report["dates"][2]["priceResidualStructure"]
    assert common["spatiallyComparableHours"] == 24
    assert common["hourlyUniformResidualHours"] == 24
    assert common["rawMaeOnSameEligibleNodes"] == pytest.approx(100)
    assert common["bestExPostHourlyUniformShiftMae"] == pytest.approx(0)
    assert common["bestExPostUniformShiftFraction"] == pytest.approx(1)
    assert spread["rawMaeOnSameEligibleNodes"] == pytest.approx(50)
    assert spread["bestExPostHourlyUniformShiftMae"] == pytest.approx(50)
    assert spread["worstObservedResidualRange"] == pytest.approx(100)
    assert spread["hourlyUniformResidualHours"] == 0
    assert clean["rawMaeOnSameEligibleNodes"] == pytest.approx(0)
    assert clean["bestExPostUniformShiftFraction"] is None
    assert report["exPostCommonShiftIsNotProspectivePriceCorrection"] is True
    assert report["priceRuleVerified"] is False
    assert report["validatedNewBids"] is False
    serial = json.dumps(report, ensure_ascii=False)
    assert '"G1"' not in serial
    assert '"G2"' not in serial
    assert '"LINE-AB"' not in serial
    h = report["dates"][0]["hours"][0]
    assert h["nodal_price_median_centered_mae"] == pytest.approx(0)
    assert "NOT" in report["warning"] or "EX-POST" in report["warning"]


def test_full_hourly_metric_defaults_keep_older_callers_compatible():
    from powerbid.historical_validation import HourlyError

    h = HourlyError(1, 0, 0, 0, 0, 0, 0)
    assert asdict(h)["nodal_price_median_signed_residual"] is None
    assert asdict(h)["nodal_price_compared_nodes_for_shape"] == 0
