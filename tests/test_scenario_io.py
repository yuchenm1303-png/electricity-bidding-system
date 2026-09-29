import json

from powerbid.scenario_io import load_scenario


def test_load_scenario_preserves_data_provenance(tmp_path) -> None:
    path = tmp_path / "scenario.json"
    path.write_text(
        json.dumps(
            {
                "name": "course case",
                "description": "Provided by the course",
                "data_source": "course",
                "demand_mw": 100,
                "interval_hours": 1,
                "target_unit_id": "G1",
                "offers": [
                    {
                        "unit_id": "G1",
                        "quantity_mw": 100,
                        "bid_price": 50,
                        "marginal_cost": 40,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    scenario = load_scenario(path)

    assert scenario.data_source == "course"
    assert scenario.description == "Provided by the course"
