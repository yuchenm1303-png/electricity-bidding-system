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
