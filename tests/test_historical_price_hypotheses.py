"""Historical price-ceiling hypothesis tests: reporting transform is not PMSS pricing."""
import pytest
from test_historical_validation import _fixture

from powerbid.historical_price_hypotheses import audit_historical_price_caps


def _high_bid_sample():
    raw = _fixture()
    # G1 at A offers 60; G2 at B is needed to cover 130MW local demand.
    # G2 high offer becomes the modeled B-node marginal price.
    raw["unitBids"]["G2"]["datas"][0]["segmentDatas"][0]["price"] = 7000
    for row in raw["results"]["nodalPrices"]:
        if row["element_id"] == "B":
            row["lmp"] = [1001.0] * 24
    return raw


def test_hypothetical_cap_1001_exactly_fits_two_bus_history_but_not_current_rule():
    raw = _high_bid_sample()
    study = audit_historical_price_caps(
        raw, hypothetical_ceilings=(1000, 1001)
    )
    assert study.observed_points == 48
    assert study.node_count == 2
    assert study.hypotheses[0].mae == pytest.approx(2999.5)
    assert study.hypotheses[1].mae == pytest.approx(0.5)
    assert study.hypotheses[2].mae == pytest.approx(0.0)
    assert study.hypotheses[2].matching_points == 48
    assert study.hypotheses[2].improved_points_vs_uncapped == 24
    assert study.maximum_price_in_saved_original_offers == 7000
    assert study.price_ceiling_in_current_market_rule == 1000
    assert study.historical_offer_segments_above_current_rule == 1
    assert study.validated_new_bids is False
    assert "NOT proof" in study.model_label
    # The uploaded historical offer was not rewritten/clipped.
    assert raw["unitBids"]["G2"]["datas"][0]["segmentDatas"][0]["price"] == 7000


def test_normal_bid_price_history_is_unaffected_by_explicit_cap_hypotheses():
    report = audit_historical_price_caps(
        _fixture(), hypothetical_ceilings=(1000, 1001)
    )
    assert report.hypotheses[0].mae == pytest.approx(0)
    assert report.hypotheses[1].mae == pytest.approx(0)
    assert report.hypotheses[2].mae == pytest.approx(0)
    assert report.hypotheses[0].matching_points == 48
    assert all(hour.raw_mismatching_points == 0 for hour in report.hours)


def test_hypothetical_cap_can_make_price_fit_worse():
    report = audit_historical_price_caps(
        _fixture(), hypothetical_ceilings=(20.0,)
    )
    assert report.hypotheses[1].mae > report.hypotheses[0].mae
    assert report.hypotheses[1].worsened_points_vs_uncapped > 0


def test_missing_observed_price_is_not_imputed_and_coverage_is_explicit():
    raw = _high_bid_sample()
    raw["results"]["nodalPrices"][0]["lmp"][3] = None
    report = audit_historical_price_caps(raw)
    assert report.expected_points == 48
    assert report.observed_points == 47
    assert report.hours[3].observed_points == 1
    assert all(hyp.observed_points == 47 for hyp in report.hypotheses)


def test_history_provenance_and_strict_node_id_checks():
    raw = _fixture()
    raw["historicalBacktestOnly"] = False
    with pytest.raises(ValueError, match="historical"):
        audit_historical_price_caps(raw)
    raw = _fixture()
    raw["results"]["nodalPrices"][0]["element_id"] = "nonexistent"
    with pytest.raises(ValueError, match="IDs differ"):
        audit_historical_price_caps(raw)
    raw = _fixture()
    with pytest.raises(ValueError, match="Duplicate"):
        audit_historical_price_caps(raw, hypothetical_ceilings=(1001, 1001))


def test_hypothetical_prices_never_exceed_budget_or_allow_unbounded_tuning():
    raw = _fixture()
    for caps in ((float("nan"),), (-1,), (1,2,3,4,5)):
        with pytest.raises(ValueError, match="ceilings|hypotheses"):
            audit_historical_price_caps(raw, hypothetical_ceilings=caps)
