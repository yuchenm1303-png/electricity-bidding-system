import pytest

from powerbid.pmss_result_loader import read_market_results
from powerbid.pmss_results import parse_branch_flows, parse_nodal_prices


def _metric(value):
    return {
        "name": "period",
        "period": 24,
        "datas": [value] * 24,
        "average": value,
        "sum": value * 24,
    }


def _tree(market: str, element: str):
    return [
        {"key": "DA", "title": "日前", "children": [
            {"key": f"DA-{element}", "leaf": True},
        ]},
        {"key": "RT", "title": "实时", "children": [
            {"key": f"RT-{element}", "leaf": True},
        ]},
    ]


class FakeResults:
    def __init__(self, *, incomplete=False):
        self.calls = []
        self.incomplete = incomplete

    def get_unit_result_tree(self, case_id):
        return _tree("DA", "unit-1")

    def get_nodal_tree(self, case_id):
        return _tree("DA", "bus-1")

    def get_branch_tree(self, case_id):
        return _tree("DA", "line-1")

    def get_unit_results(self, **kwargs):
        self.calls.append(("unit", kwargs))
        return {
            "periodNum": 24,
            "datas": [] if self.incomplete else [
                {
                    "elementId": "unit-1",
                    "elementName": "Test unit",
                    "marketTypeAtom": "DA" if kwargs["da_ids"] else "RT",
                    "power": _metric(10),
                    "price": _metric(50),
                    "income": _metric(500),
                }
            ],
        }

    def get_nodal_prices(self, **kwargs):
        self.calls.append(("node", kwargs))
        return {
            "period": 24,
            "data": [
                {
                    "elementId": "bus-1",
                    "elementName": "Test bus",
                    "marketTypeAtom": "DA" if kwargs["da_ids"] else "RT",
                    "powerFlow": _metric(53),
                }
            ],
        }

    def get_branch_flows(self, **kwargs):
        self.calls.append(("branch", kwargs))
        return {
            "period": 24,
            "data": [
                {
                    "elementId": "line-1",
                    "elementName": "Test branch",
                    "marketTypeAtom": "DA" if kwargs["da_ids"] else "RT",
                    "powerFlow": _metric(-40),
                    "beginNodePrice": _metric(53),
                    "endNodePrice": _metric(51),
                    "shadowPrice": _metric(2),
                    "blockSurplus": _metric(80),
                }
            ],
        }


def test_nodal_parser_uses_power_flow_as_lmp_per_live_frontend():
    data = {"period": 24, "data": [
        {
            "elementId": "bus-1", "elementName": "Bus",
            "marketTypeAtom": "DA", "powerFlow": _metric(53),
        },
    ]}
    row = parse_nodal_prices(data)[0]
    assert row.lmp == (53.0,) * 24
    with pytest.raises(ValueError, match="24-hour"):
        parse_nodal_prices({**data, "period": 23})


def test_branch_parser_reads_all_five_real_series():
    data = FakeResults().get_branch_flows(da_ids=["line-1"])
    row = parse_branch_flows(data)[0]
    assert row.flow_mw[0] == -40
    assert row.from_node_price[0] == 53
    assert row.to_node_price[0] == 51
    assert row.shadow_price[0] == 2
    assert row.congestion_surplus[0] == 80


def test_all_result_tabs_use_unprefixed_market_specific_ids():
    fake = FakeResults()
    loaded = read_market_results(fake, case_id="case-1", market_type="DA")
    assert len(loaded["unitResults"]) == 1
    assert len(loaded["nodalPrices"]) == 1
    assert len(loaded["branchFlows"]) == 1
    assert [kind for kind, _ in fake.calls] == ["unit", "node", "branch"]
    assert [args["da_ids"] for _, args in fake.calls] == [
        ["unit-1"], ["bus-1"], ["line-1"],
    ]
    assert all(args["rt_ids"] == [] for _, args in fake.calls)
    assert loaded["branchFlows"][0]["flow_mw"] == (-40.0,) * 24


def test_incomplete_result_is_not_misreported_as_success():
    with pytest.raises(ValueError, match="selected 1, received 0"):
        read_market_results(FakeResults(incomplete=True), case_id="case-1")


def test_real_time_uses_rt_only():
    fake = FakeResults()
    read_market_results(fake, case_id="case-1", market_type="RT")
    assert all(args["da_ids"] == [] for _, args in fake.calls)
    assert [args["rt_ids"] for _, args in fake.calls] == [
        ["unit-1"], ["bus-1"], ["line-1"],
    ]
