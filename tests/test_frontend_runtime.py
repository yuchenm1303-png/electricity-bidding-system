"""Execute the real Streamlit app in CI to catch frontend regressions."""

from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def test_default_workspace_and_profit_report():
    at = AppTest.from_file(str(APP), default_timeout=45).run()
    assert not at.exception, [item.message for item in at.exception]
    assert at.button
    at.button[0].click().run()
    assert not at.exception, [item.message for item in at.exception]
    assert any("推荐报价" in item.label for item in at.metric)


def test_risk_mode_report():
    at = AppTest.from_file(str(APP), default_timeout=45).run()
    assert not at.exception, [item.message for item in at.exception]
    at.sidebar.selectbox[2].set_value("不确定性 / 风险分析").run()
    assert not at.exception, [item.message for item in at.exception]
    at.button[0].click().run()
    assert not at.exception, [item.message for item in at.exception]
    assert any("期望利润" in item.label for item in at.metric)
