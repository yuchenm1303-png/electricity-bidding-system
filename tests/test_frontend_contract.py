"""Static frontend smoke checks that do not require Streamlit at CI import time."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "app" / "streamlit_app.py"
DESIGN = ROOT / "app" / "design_system.py"
THEME_CONFIG = ROOT / ".streamlit" / "config.toml"


def test_frontend_python_compiles():
    """Both frontend modules must remain syntactically valid after design edits."""
    for path in (VIEW, DESIGN):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_design_is_shared_and_offline_friendly():
    view = VIEW.read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")
    assert "from design_system import APP_CSS" in view
    assert 'st.markdown(APP_CSS, unsafe_allow_html=True)' in view
    assert ".pb-hero" in design
    assert ".pb-empty" in design
    assert "@media (max-width:900px)" in design
    assert "prefers-reduced-motion:reduce" in design
    assert "@import" not in design
    assert "https://" not in design
    assert THEME_CONFIG.exists()


def test_report_persists_and_marks_stale_inputs():
    view = VIEW.read_text(encoding="utf-8")
    assert 'st.session_state["pb_report"] = saved_report' in view
    assert 'saved_report["signature"] != current_signature' in view
    assert 'if report_mode == "单场景利润最大化":' in view
    assert 'disabled=not (valid_range and valid_target)' in view
    assert "数据来源 / {source_label}" in view
