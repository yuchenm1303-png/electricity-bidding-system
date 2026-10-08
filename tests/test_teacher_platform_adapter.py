import pytest

from powerbid.adapters.teacher_platform import (
    TeacherPlatformAdapter,
    TeacherPlatformContext,
    TeacherPlatformError,
)


def test_build_unit_bid_payload_matches_pmss_shape():
    payload = TeacherPlatformAdapter.build_unit_bid_payload(
        scope_id="scope-da",
        unit_id="unit-1",
        period_num=24,
        min_tech_power_cost=12,
        start_cost_hot=13,
        start_cost_warm=14,
        start_cost_cold=15,
        segments=[
            {"startPower": 0, "endPower": 200, "price": 250},
            {"startPower": 200, "endPower": 500, "price": 320},
        ],
    )

    assert payload["scopeId"] == "scope-da"
    assert payload["unitId"] == "unit-1"
    assert payload["datas"][0]["startPeriod"] == 1
    assert payload["datas"][0]["endPeriod"] == 24
    assert payload["datas"][0]["segmentDatas"] == [
        {
            "startPower": 0.0,
            "endPower": 200.0,
            "price": 250.0,
            "segmentOrder": 1,
        },
        {
            "startPower": 200.0,
            "endPower": 500.0,
            "price": 320.0,
            "segmentOrder": 2,
        },
    ]


def test_validate_segments_rejects_gap_and_too_many_segments():
    TeacherPlatformAdapter.validate_segments(
        [
            {"startPower": 0, "endPower": 200, "price": 250},
            {"startPower": 200, "endPower": 500, "price": 320},
        ],
        max_segments=5,
        price_min=0,
        price_max=1000,
        max_power=500,
    )

    with pytest.raises(ValueError, match="previous endPower"):
        TeacherPlatformAdapter.validate_segments(
            [
                {"startPower": 0, "endPower": 200, "price": 250},
                {"startPower": 220, "endPower": 500, "price": 320},
            ],
            max_segments=5,
            price_min=0,
            price_max=1000,
        )

    with pytest.raises(ValueError, match="Too many segments"):
        TeacherPlatformAdapter.validate_segments(
            [
                {"startPower": i * 10, "endPower": (i + 1) * 10, "price": 100 + i}
                for i in range(6)
            ],
            max_segments=5,
            price_min=0,
            price_max=1000,
        )


def test_clearing_payload_is_explicit_and_minimal():
    assert TeacherPlatformAdapter.build_clearing_payload(
        case_id="case-1",
        comment="audit-tag",
    ) == {"caseId": "case-1", "comment": "audit-tag"}


def test_context_resolves_day_ahead_scope():
    context = TeacherPlatformContext(
        project={},
        cases=(),
        market_system={
            "scopes": [
                {
                    "tmSceneDateKey": "date-1",
                    "datas": [
                        {"selfSort": "DA", "scopeId": "scope-da"},
                        {"selfSort": "RT", "scopeId": "scope-rt"},
                    ],
                }
            ]
        },
        units=(),
    )

    assert context.scope_id(
        case={"caseId": "case-1", "tmSceneDateKey": "date-1"},
        market_type_atom="DA",
    ) == "scope-da"

    with pytest.raises(TeacherPlatformError):
        context.scope_id(
            case={"caseId": "case-2", "tmSceneDateKey": "missing"},
            market_type_atom="DA",
        )
