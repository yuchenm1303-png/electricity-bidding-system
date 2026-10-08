"""Static frontend smoke checks that do not require Streamlit at CI import time."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "app" / "streamlit_app.py"
DESIGN = ROOT / "app" / "design_system.py"
CSS = ROOT / "app" / "assets" / "powerbid.css"
THEME_CONFIG = ROOT / ".streamlit" / "config.toml"


def test_frontend_python_compiles():
    """Both frontend modules must remain syntactically valid after design edits."""
    for path in (VIEW, DESIGN):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_design_is_shared_and_offline_friendly():
    view = VIEW.read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "from design_system import APP_CSS" in view
    assert 'st.markdown(APP_CSS, unsafe_allow_html=True)' in view
    assert "CSS_PATH.read_text" in design
    assert ".pb-hero" in css
    assert ".pb-empty" in css
    assert "@media (max-width:950px)" in css
    assert ".pb-kpi" in css
    assert ".pb-chart-heading" in css
    assert ".pb-side-summary" in css
    assert "prefers-reduced-motion:reduce" in css
    assert "@import" not in css
    assert "https://" not in css
    assert THEME_CONFIG.exists()


def test_report_persists_and_marks_stale_inputs():
    view = VIEW.read_text(encoding="utf-8")
    assert 'st.session_state["pb_report"] = saved_report' in view
    assert 'saved_report["signature"] != current_signature' in view
    assert 'if report_mode == "单场景利润最大化":' in view
    assert 'disabled=not (valid_range and valid_target)' in view
    assert "数据源 · {source_label}" in view
    assert "def metric_tile(" in view
    assert "def chart_heading(" in view
    assert "教学模拟 · 非实时市场" in view
    assert "POWERBID_PLATFORM_BASE_URL" in view
    assert "老师仿真平台 · 只读联调" in view
    assert "teacher_platform_card" in view


def test_pmss_page_compiles_and_stays_read_only():
    page = ROOT / "app" / "pages" / "1_PMSS_5段报价.py"
    source = page.read_text(encoding="utf-8")
    ast.parse(source, filename=str(page))
    assert "analyze_historical_network" in source
    assert "compare_baseline_to_pmss" in source
    assert 'raw.get("loadSourceKind")' in source
    assert "save_unit_bid(" not in source
    assert "run_clearing(" not in source
