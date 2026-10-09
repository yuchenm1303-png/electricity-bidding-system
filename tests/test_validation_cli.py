"""Private file CLI smoke tests; never copies raw PMSS data into the report."""
import json
import os

import pytest
from test_historical_validation import _fixture

from scripts.validate_pmss_history import main


def _cases(tmp_path, count):
    files = []
    for i in range(1, count + 1):
        path = tmp_path / f"case-{i}.json"
        path.write_text(
            json.dumps(_fixture(f"2025-09-{i:02d}")), encoding="utf-8"
        )
        files.append(path)
    return files


def test_cli_three_day_holdout_can_write_only_metrics_to_private_new_file(tmp_path):
    days = _cases(tmp_path, 3)
    report = tmp_path / "output.json"
    rc = main([
        "--max-unit-mae-mw", "1",
        "--max-nodal-price-mae", "1",
        "--output", str(report),
        *(str(day) for day in days),
    ])
    assert rc == 0
    result = json.loads(report.read_text("utf-8"))
    assert result["verdict"]["status"] == "HISTORICAL_BASELINE_WITHIN_TOLERANCE"
    assert result["verdict"]["validated_new_bids"] is False
    assert result["verdict"]["holdout_case_dates"] == ["2025-09-03"]
    assert "unitBids" not in result
    assert "unitTree" not in result
    if os.name == "posix":
        assert report.stat().st_mode & 0o077 == 0

    with pytest.raises(SystemExit):
        main([
            "--max-unit-mae-mw", "1", "--max-nodal-price-mae", "1",
            "--output", str(report), *(str(day) for day in days),
        ])


def test_cli_single_day_returns_nonzero_for_insufficient_evidence(tmp_path, capsys):
    days = _cases(tmp_path, 1)
    rc = main([
        "--max-unit-mae-mw", "1", "--max-nodal-price-mae", "1",
        str(days[0]),
    ])
    assert rc == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"]["status"] == "NOT_VALIDATED"
    assert printed["verdict"]["historical_only"]
