"""Synthetic-only contract tests; never copy PMSS course data into Git."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from powerbid.pmss_model_import import SCHEMA_VERSION, build_standard_pmss_model
from powerbid.pmss_scene_constraint_evidence import summarize_scene_constraint_evidence

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    sample = json.loads((ROOT / "data/examples/synthetic_dc_pmss.json").read_text(encoding="utf-8"))
    sample.update(
        {
            "caseDate": "2025-09-01",
            "loadSourceKind": "PMSS_DA_SCENE_LOAD_INPUT",
            "historicalBacktestOnly": True,
            "loadNodeCount": 2,
        }
    )
    totals = sample["demandForecastMw"]

    def curve(values):
        return {f"t{i:02d}": value for i, value in enumerate(values, 1)}

    grid = {
        "nodes": {
            "datas": [
                {"id": "A", "name": "BusA", "cookie": "PRIVATE-NO-EXPORT"},
                {"id": "B", "name": "BusB"},
            ]
        },
        "lines": {
            "datas": [
                {
                    "id": "LineAB",
                    "bgnNodeId": "A",
                    "endNodeId": "B",
                    "ratio": 1,
                    "x": 0.1,
                    "ratedMw": 200,
                    "secret": "PRIVATE-NO-EXPORT",
                }
            ]
        },
        "units": {
            "datas": [
                {"id": "G1", "nodeId": "A"},
                {"id": "G2", "nodeId": "B"},
            ]
        },
        "loads": {
            "data": {
                "datas": [
                    {"elementId": "total", "elementName": "统调负荷", "da": curve(totals)},
                    {"elementId": "A", "elementName": "BusA", "da": curve([0] * 24)},
                    {"elementId": "B", "elementName": "BusB", "da": curve(totals)},
                ]
            }
        },
    }

    def values(value):
        return [value] * 24

    sample["results"] = {
        "marketTypeAtom": "DA",
        "periodNum": 24,
        "unitResults": [
            {
                "unit_id": unit,
                "name": unit,
                "market_type": "DA",
                "accepted_mw": values(0),
                "clearing_prices": values(0),
                "income": values(0),
            }
            for unit in ("G1", "G2")
        ],
        "nodalPrices": [
            {
                "element_id": node,
                "name": node,
                "market_type": "DA",
                "lmp": values(0),
            }
            for node in ("A", "B")
        ],
        "branchFlows": [
            {
                "element_id": "LineAB",
                "name": "LineAB",
                "market_type": "DA",
                **{
                    name: values(0)
                    for name in (
                        "flow_mw",
                        "from_node_price",
                        "to_node_price",
                        "shadow_price",
                        "congestion_surplus",
                    )
                },
            }
        ],
    }
    sample["unlistedCookie"] = "PRIVATE-NO-EXPORT"
    sample["results"]["unitResults"][0]["sessionId"] = "PRIVATE-NO-EXPORT"
    return sample, grid


class PMSSStandardImportTest(unittest.TestCase):
    def model(self, sample=None, grid=None, **kwargs):
        if sample is None or grid is None:
            sample, grid = fixture()
        return build_standard_pmss_model(
            sample,
            grid,
            grid_case_date="2025-09-01",
            expected_counts=(2, 1, 2),
            **kwargs,
        )

    def test_import_complete_synthetic_case_and_source_allowlist(self):
        model = self.model()
        self.assertEqual(model["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(model["importValidation"]["busCount"], 2)
        self.assertEqual(model["importValidation"]["historicalNodeCount"], 2)
        self.assertEqual(len(model["dcNetwork"]["hourlyDemandMw"]["B"]), 24)
        self.assertEqual(len(model["results"]["unitResults"]), 2)
        self.assertFalse(model["generatorConstraints"]["physicalUCVerified"])
        self.assertFalse(model["importValidation"]["pmssClearingParityVerified"])
        self.assertNotIn("PRIVATE-NO-EXPORT", json.dumps(model))
        self.assertNotIn("sessionId", json.dumps(model))

    def test_default_target_counts_are_strict(self):
        source, grid = fixture()
        with self.assertRaisesRegex(ValueError, "topology counts incomplete"):
            build_standard_pmss_model(source, grid, grid_case_date="2025-09-01")

    def test_case_date_and_provenance_cannot_be_inferred(self):
        source, grid = fixture()
        with self.assertRaisesRegex(ValueError, "Grid case date"):
            build_standard_pmss_model(
                source, grid, grid_case_date="2025-09-02", expected_counts=(2, 1, 2)
            )
        source["historicalBacktestOnly"] = False
        with self.assertRaisesRegex(ValueError, "not a forward prediction"):
            self.model(source, grid)

    def test_generator_and_network_ids_cannot_be_silently_replaced(self):
        source, grid = fixture()
        grid["units"]["datas"][0]["id"] = "unrelated-unit"
        with self.assertRaises(ValueError):
            self.model(source, grid)
        source, grid = fixture()
        grid["lines"]["datas"][0]["endNodeId"] = "not-a-bus"
        with self.assertRaises(ValueError):
            self.model(source, grid)

    def test_load_hourly_and_cross_source_totals_are_strict(self):
        source, grid = fixture()
        grid["loads"]["data"]["datas"][2]["da"]["t05"] += 1
        with self.assertRaisesRegex(ValueError, "load mismatch|nodal/system"):
            self.model(source, grid)
        source, grid = fixture()
        source["demandForecastMw"][0] += 1
        with self.assertRaises(ValueError):
            self.model(source, grid)
        source, grid = fixture()
        source["demandForecastMw"][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            self.model(source, grid)

    def test_historical_id_and_24h_series_validation(self):
        source, grid = fixture()
        source["results"]["nodalPrices"][0]["element_id"] = "wrong"
        with self.assertRaisesRegex(ValueError, "element ID"):
            self.model(source, grid)
        source, grid = fixture()
        source["results"]["unitResults"][0]["accepted_mw"].pop()
        with self.assertRaisesRegex(ValueError, "24 hourly"):
            self.model(source, grid)
        source, grid = fixture()
        source["results"]["branchFlows"].clear()
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.model(source, grid)

    def test_legacy_native_pmss_results_reuse_existing_parsers(self):
        source, grid = fixture()
        native = {
            "marketTypeAtom": "DA",
            "periodNum": 24,
            "unitResults": [],
            "nodalPrices": [],
            "branchFlows": [],
        }

        def wrapped(v):
            return {"datas": list(v)}

        for row in source["results"]["unitResults"]:
            native["unitResults"].append(
                {
                    "elementId": row["unit_id"],
                    "elementName": row["name"],
                    "marketTypeAtom": "DA",
                    "power": wrapped(row["accepted_mw"]),
                    "price": wrapped(row["clearing_prices"]),
                    "income": wrapped(row["income"]),
                }
            )
        for row in source["results"]["nodalPrices"]:
            native["nodalPrices"].append(
                {
                    "elementId": row["element_id"],
                    "elementName": row["name"],
                    "marketTypeAtom": "DA",
                    "powerFlow": wrapped(row["lmp"]),
                }
            )
        for row in source["results"]["branchFlows"]:
            native["branchFlows"].append(
                {
                    "elementId": row["element_id"],
                    "elementName": row["name"],
                    "marketTypeAtom": "DA",
                    "powerFlow": wrapped(row["flow_mw"]),
                    "beginNodePrice": wrapped(row["from_node_price"]),
                    "endNodePrice": wrapped(row["to_node_price"]),
                    "shadowPrice": wrapped(row["shadow_price"]),
                    "blockSurplus": wrapped(row["congestion_surplus"]),
                }
            )
        source["results"] = native
        model = self.model(source, grid)
        self.assertEqual(len(model["results"]["unitResults"]), 2)
        self.assertNotIn("elementName", model["results"]["unitResults"][0])

    def test_technical_switches_are_anonymous_not_physical_uc(self):
        source, grid = fixture()
        calculate = {
            "rowCount": 2,
            "datas": [
                {"ifConRamp": 1, "credential": "PRIVATE-NO-EXPORT"},
                {"ifConRamp": 0},
            ],
        }
        initial = {"rowCount": 2, "datas": [{"power": 9}, {"power": 0}]}
        evidence = summarize_scene_constraint_evidence(calculate, initial, expected_units=2)
        model = self.model(source, grid, scene_constraint_evidence=evidence)
        self.assertFalse(model["generatorConstraints"]["jointMilpReady"])
        self.assertNotIn("PRIVATE-NO-EXPORT", json.dumps(model))
        falsified = copy.deepcopy(evidence)
        falsified["jointMilpReady"] = True
        with self.assertRaisesRegex(ValueError, "cannot assert"):
            self.model(source, grid, scene_constraint_evidence=falsified)

    def test_output_writer_refuses_git_and_overwrite(self):
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("private_pmss_cli", ROOT / "scripts/import_pmss_model.py")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaisesRegex(ValueError, "Git worktree"):
            module._write_private(ROOT / "tests/NEVER-PUT-PRIVATE-PMSS-HERE.json", {"sample": True})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.json"
            module._write_private(path, {"sample": True})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                module._write_private(path, {"sample": False})


if __name__ == "__main__":
    unittest.main()
