import pytest

from powerbid.pmss_load import parse_da_nodal_loads


def load_row(name, amount):
    return {
        "elementId": name,
        "da": {f"t{i:02d}": amount for i in range(1, 25)},
        "ust": {f"t{i:02d}": amount + 10 for i in range(1, 25)},
    }


def payload(rows, row_count=None):
    return {
        "periodNum": 24,
        "data": {
            "rowCount": len(rows) if row_count is None else row_count,
            "datas": rows,
        },
    }


def test_da_load_sums_all_nodes():
    result = parse_da_nodal_loads(payload([load_row("n1", 75), load_row("n2", 125)]))
    assert result.total_load_mw == (200.0,) * 24
    assert result.node_count == 2


def test_da_load_rejects_incomplete_page():
    with pytest.raises(ValueError, match="incomplete"):
        parse_da_nodal_loads(payload([load_row("n1", 75)], 40))


def test_da_load_rejects_missing_hour():
    row = load_row("n1", 50)
    del row["da"]["t24"]
    with pytest.raises(ValueError, match="t24"):
        parse_da_nodal_loads(payload([row]))


def test_pmss_total_row_is_not_double_counted():
    row = load_row("aggregate", 200)
    row["elementName"] = "统调负荷"
    result = parse_da_nodal_loads(
        payload([row, load_row("n1", 75), load_row("n2", 125)], row_count=2)
    )
    assert result.node_count == 2
    assert result.total_load_mw == (200.0,) * 24


def test_pmss_total_row_must_match_nodal_sum():
    row = load_row("aggregate", 220)
    row["elementName"] = "统调负荷"
    with pytest.raises(ValueError, match="does not match node sum"):
        parse_da_nodal_loads(
            payload([row, load_row("n1", 75), load_row("n2", 125)], row_count=2)
        )


def test_da_load_adapter_calls_read_only_list_endpoint():
    from powerbid.adapters.teacher_platform import TeacherPlatformAdapter

    client = object.__new__(TeacherPlatformAdapter)
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs["json_body"]))
        return {"periodNum": 24, "data": {"datas": []}}

    client._request = fake_request
    client.get_da_nodal_loads(pm_scene_id="scene-A", pm_scene_date_key="date-A")
    assert calls == [(
        "POST",
        "scene/loadFc/list",
        {
            "ids": [],
            "pageNo": 1,
            "pageSize": 999,
            "sceneDateKey": "date-A",
            "sceneId": "scene-A",
        },
    )]


def test_scene_snapshot_uses_da_loads_without_fallback_to_dispatch(monkeypatch):
    from powerbid import pmss_export

    class Fake:
        def get_da_nodal_loads(self, **kwargs):
            assert kwargs == {
                "pm_scene_id": "scene-1",
                "pm_scene_date_key": "date-1",
            }
            aggregate = load_row("sum", 200)
            aggregate["elementName"] = "统调负荷"
            return payload(
                [aggregate, load_row("bus-1", 75), load_row("bus-2", 125)],
                row_count=2,
            )

    def fake_export(adapter, **kwargs):
        assert kwargs["demand_forecast_mw"] == [200] * 24
        assert "historical scenario input" in kwargs["forecast_source"]
        return {"unitTree": [], "unitBids": {}, "marketSystem": {}}

    monkeypatch.setattr(pmss_export, "build_readonly_snapshot", fake_export)
    result = pmss_export.build_da_scene_snapshot(
        Fake(),
        context=object(),
        case={
            "pmSceneId": "scene-1",
            "pmSceneDateKey": "date-1",
            "caseDate": "2025-09-01",
        },
        include_results=False,
    )
    assert result["historicalBacktestOnly"]
    assert result["loadNodeCount"] == 2
    assert result["loadSourceKind"] == "PMSS_DA_SCENE_LOAD_INPUT"
