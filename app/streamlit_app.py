from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from powerbid.adapters.pypsa_engine import PyPSAClearingEngine  # noqa: E402
from powerbid.clearing.uniform_price import UniformPriceClearingEngine  # noqa: E402
from powerbid.models import MarketScenario, Offer  # noqa: E402
from powerbid.optimizer import GridSearchBidOptimizer, price_grid  # noqa: E402
from powerbid.risk import RiskAwareBidOptimizer, build_stress_cases  # noqa: E402
from powerbid.scenario_io import load_scenario  # noqa: E402

st.set_page_config(
    page_title="PowerBid Lab",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


APP_CSS = r"""
<style>
:root {
    --pb-blue: #4f8cff;
    --pb-cyan: #27d3c2;
    --pb-violet: #8b7cf6;
    --pb-red: #f06b75;
    --pb-amber: #f0b45f;
    --pb-radius-xl: 24px;
    --pb-radius-lg: 18px;
    --pb-radius-md: 13px;
    --pb-line: color-mix(in srgb, var(--text-color) 9%, transparent);
    --pb-line-strong: color-mix(in srgb, var(--text-color) 14%, transparent);
    --pb-muted: color-mix(in srgb, var(--text-color) 56%, transparent);
    --pb-surface: color-mix(in srgb, var(--secondary-background-color) 72%, transparent);
    --pb-surface-2: color-mix(in srgb, var(--secondary-background-color) 88%, transparent);
}

html, body, [class*="css"] {
    font-family: Inter, "SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont,
        "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}

html { scroll-behavior: smooth; }
body { letter-spacing: -.008em; }

.stApp {
    background:
        radial-gradient(circle at 76% -12%, rgba(79, 140, 255, .08), transparent 29rem),
        radial-gradient(circle at 12% 18%, rgba(39, 211, 194, .045), transparent 25rem),
        linear-gradient(180deg, color-mix(in srgb, var(--background-color) 98%, #0b1320), var(--background-color));
}

.stApp::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    opacity: .15;
    background-image:
        linear-gradient(var(--pb-line) 1px, transparent 1px),
        linear-gradient(90deg, var(--pb-line) 1px, transparent 1px);
    background-size: 52px 52px;
    mask-image: linear-gradient(to bottom, rgba(0,0,0,.18), transparent 58%);
}

[data-testid="stHeader"] { height: 2.4rem; background: transparent; }
[data-testid="stDecoration"] { display: none; }
#MainMenu, footer { visibility: hidden; }
[data-testid="stAppViewBlockContainer"] { max-width: 1510px; padding: 1.2rem 2.2rem 4.5rem; }

/* ---------- Sidebar ---------- */
section[data-testid="stSidebar"] {
    width: 306px !important;
    min-width: 306px !important;
    background:
        radial-gradient(circle at 22% 0%, rgba(79, 140, 255, .055), transparent 17rem),
        color-mix(in srgb, var(--secondary-background-color) 96%, var(--background-color));
    border-right: 1px solid var(--pb-line);
    box-shadow: 14px 0 42px rgba(0, 0, 0, .035);
}
section[data-testid="stSidebar"] > div { padding-top: .55rem; }
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding: .2rem .72rem 1rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .46rem; }
[data-testid="stSidebar"] .stMarkdown p { margin-bottom: 0; }
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
    font-size: .73rem !important;
    line-height: 1.2 !important;
    font-weight: 650 !important;
    color: color-mix(in srgb, var(--text-color) 68%, transparent) !important;
}
.pb-side-brand { display:flex; align-items:center; gap:.66rem; padding:.32rem .18rem .76rem; margin-bottom:.22rem; }
.pb-side-logo {
    position:relative; width:35px; height:35px; flex:0 0 35px;
    border-radius:11px; display:grid; place-items:center; overflow:hidden; color:white;
    background:linear-gradient(145deg,#497ff2 0%,#4f8cff 48%,#21baa9 108%);
    box-shadow:0 7px 20px rgba(46,113,255,.18), inset 0 1px rgba(255,255,255,.20);
}
.pb-side-logo::after { content:""; position:absolute; inset:1px; border-radius:10px; border:1px solid rgba(255,255,255,.13); }
.pb-side-title { font-size:.88rem; line-height:1.12; font-weight:760; letter-spacing:-.025em; color:var(--text-color); }
.pb-side-subtitle { margin-top:.14rem; font-size:.61rem; font-weight:560; letter-spacing:.03em; color:color-mix(in srgb,var(--text-color) 41%,transparent); }
.pb-live-dot { display:inline-block; width:7px; height:7px; margin-right:.32rem; border-radius:999px; background:var(--pb-cyan); box-shadow:0 0 0 4px rgba(39,211,194,.09); }
.pb-side-group-head { display:flex; align-items:center; justify-content:space-between; gap:.7rem; padding:.02rem .02rem .42rem; }
.pb-side-group-title { display:flex; align-items:center; gap:.46rem; font-size:.70rem; font-weight:760; color:color-mix(in srgb,var(--text-color) 86%,transparent); }
.pb-side-index { display:grid; place-items:center; width:22px; height:22px; border-radius:7px; background:rgba(79,140,255,.10); border:1px solid rgba(79,140,255,.15); color:var(--pb-blue); font-size:.60rem; font-weight:800; }
.pb-side-group-meta { font-size:.56rem; font-weight:700; letter-spacing:.10em; text-transform:uppercase; color:color-mix(in srgb,var(--text-color) 31%,transparent); }
.st-key-sidebar_market [data-testid="stVerticalBlockBorderWrapper"],
.st-key-sidebar_bid [data-testid="stVerticalBlockBorderWrapper"],
.st-key-sidebar_risk [data-testid="stVerticalBlockBorderWrapper"] {
    border:1px solid color-mix(in srgb,var(--text-color) 7%,transparent) !important;
    border-radius:14px !important;
    background:linear-gradient(145deg,rgba(79,140,255,.025),transparent 48%),color-mix(in srgb,var(--secondary-background-color) 48%,transparent) !important;
    box-shadow:inset 0 1px rgba(255,255,255,.012) !important;
}
.st-key-sidebar_market [data-testid="stVerticalBlockBorderWrapper"] > div,
.st-key-sidebar_bid [data-testid="stVerticalBlockBorderWrapper"] > div,
.st-key-sidebar_risk [data-testid="stVerticalBlockBorderWrapper"] > div { padding:.78rem .72rem .72rem !important; }
.st-key-sidebar_market [data-testid="stVerticalBlock"],
.st-key-sidebar_bid [data-testid="stVerticalBlock"],
.st-key-sidebar_risk [data-testid="stVerticalBlock"] { gap:.52rem !important; }
[data-testid="stSidebar"] [data-baseweb="input"] > div,
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-testid="stNumberInput"] > div > div {
    min-height:2.34rem !important;
    border:1px solid color-mix(in srgb,var(--text-color) 12%,transparent) !important;
    border-radius:10px !important;
    background:color-mix(in srgb,var(--background-color) 73%,transparent) !important;
    box-shadow:inset 0 1px rgba(255,255,255,.012) !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] > div:hover,
[data-testid="stSidebar"] [data-baseweb="input"] > div:hover { border-color:color-mix(in srgb,var(--text-color) 20%,transparent) !important; }
[data-testid="stSidebar"] [data-baseweb="select"] > div:focus-within,
[data-testid="stSidebar"] [data-baseweb="input"] > div:focus-within { border-color:color-mix(in srgb,var(--pb-blue) 58%,transparent) !important; box-shadow:0 0 0 3px rgba(79,140,255,.07) !important; }
[data-testid="stSidebar"] input { font-size:.79rem !important; font-weight:620 !important; }
[data-testid="stSidebar"] [data-testid="stNumberInput"] button { width:1.68rem !important; height:1.68rem !important; min-height:1.68rem !important; margin:.18rem .12rem !important; padding:0 !important; border:0 !important; border-radius:7px !important; background:transparent !important; opacity:.54; }
[data-testid="stSidebar"] [data-testid="stNumberInput"] button:hover { opacity:1; background:color-mix(in srgb,var(--text-color) 7%,transparent) !important; }
[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] > div { padding-left:.72rem !important; padding-right:.42rem !important; }
[data-testid="stSidebar"] [data-testid="stSelectbox"] div[role="button"],
[data-testid="stSidebar"] [data-testid="stSelectbox"] span { font-size:.78rem !important; }
.pb-side-summary { display:grid; gap:.48rem; padding:.76rem .78rem .72rem; border:1px solid var(--pb-line); border-radius:13px; background:linear-gradient(120deg,rgba(79,140,255,.055),rgba(39,211,194,.018) 52%,transparent),color-mix(in srgb,var(--secondary-background-color) 70%,var(--background-color)); box-shadow:0 10px 28px rgba(0,0,0,.045); }
.pb-side-summary-head { display:flex; align-items:center; justify-content:space-between; font-size:.63rem; font-weight:730; color:color-mix(in srgb,var(--text-color) 78%,transparent); }
.pb-side-ready { display:inline-flex; align-items:center; gap:.34rem; color:var(--pb-cyan); font-size:.56rem; font-weight:760; letter-spacing:.06em; }
.pb-side-summary-grid { display:grid; grid-template-columns:1fr 1fr; gap:.38rem .6rem; }
.pb-side-summary-item span { display:block; margin-bottom:.08rem; font-size:.54rem; color:color-mix(in srgb,var(--text-color) 35%,transparent); }
.pb-side-summary-item strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:.66rem; font-weight:660; color:color-mix(in srgb,var(--text-color) 76%,transparent); }
.pb-side-footnote { margin:.35rem .1rem .1rem; text-align:center; font-size:.54rem; color:color-mix(in srgb,var(--text-color) 28%,transparent); }

/* ---------- Inputs ---------- */
[data-baseweb="input"] > div,
[data-baseweb="select"] > div,
[data-testid="stNumberInput"] > div > div,
[data-testid="stTextInput"] > div > div {
    min-height: 2.65rem;
    border-radius: 11px !important;
    border-color: var(--pb-line-strong) !important;
    background: color-mix(in srgb, var(--background-color) 70%, transparent) !important;
    box-shadow: inset 0 1px rgba(255,255,255,.018);
    transition: border-color .16s ease, background .16s ease, box-shadow .16s ease;
}
[data-baseweb="input"] > div:focus-within,
[data-baseweb="select"] > div:focus-within {
    border-color: color-mix(in srgb, var(--pb-blue) 58%, transparent) !important;
    box-shadow: 0 0 0 3px rgba(79, 140, 255, .08) !important;
}
[data-testid="stNumberInput"] button {
    width: 2rem;
    height: 2rem;
    margin: .2rem;
    border: 1px solid var(--pb-line) !important;
    border-radius: 8px !important;
    background: color-mix(in srgb, var(--secondary-background-color) 34%, transparent) !important;
    opacity: .72;
    transition: opacity .15s ease, background .15s ease;
}
[data-testid="stNumberInput"] button:hover {
    opacity: 1;
    background: color-mix(in srgb, var(--secondary-background-color) 66%, transparent) !important;
}
[data-baseweb="popover"] [role="listbox"] {
    padding: .35rem;
    border: 1px solid var(--pb-line-strong);
    border-radius: 12px;
    background: var(--secondary-background-color);
    box-shadow: 0 18px 45px rgba(0,0,0,.16);
}
[data-baseweb="popover"] [role="option"] { border-radius: 8px; font-size: .78rem; }
[data-testid="stSlider"] [data-baseweb="slider"] > div > div { height: 4px; }

/* ---------- Top bar / hero ---------- */
.pb-topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    min-height: 42px;
    margin-bottom: .9rem;
    padding: 0 .15rem;
}
.pb-breadcrumb { display:flex; align-items:center; gap:.55rem; font-size:.72rem; font-weight:610; color:var(--pb-muted); }
.pb-breadcrumb strong { color:color-mix(in srgb,var(--text-color) 82%,transparent); font-weight:700; }
.pb-top-status { display:inline-flex; align-items:center; gap:.48rem; padding:.38rem .62rem; border:1px solid var(--pb-line); border-radius:999px; background:color-mix(in srgb,var(--secondary-background-color) 58%,transparent); font-size:.68rem; font-weight:650; color:var(--pb-muted); }
.pb-hero {
    position: relative;
    overflow: hidden;
    border: 1px solid var(--pb-line);
    border-radius: var(--pb-radius-xl);
    padding: 1.7rem 1.8rem 1.55rem;
    margin-bottom: 1rem;
    background:
        linear-gradient(115deg, rgba(79, 140, 255, .105), rgba(39, 211, 194, .035) 44%, transparent 68%),
        color-mix(in srgb, var(--secondary-background-color) 72%, transparent);
    box-shadow: 0 22px 54px rgba(0, 0, 0, .055), inset 0 1px rgba(255,255,255,.025);
}
.pb-hero::before {
    content: "";
    position: absolute;
    inset: 0 0 auto auto;
    width: 420px;
    height: 100%;
    opacity: .40;
    background-image:
        linear-gradient(rgba(79,140,255,.10) 1px, transparent 1px),
        linear-gradient(90deg, rgba(79,140,255,.10) 1px, transparent 1px);
    background-size: 34px 34px;
    mask-image: linear-gradient(90deg, transparent, #000 50%);
    pointer-events: none;
}
.pb-hero::after { content:""; position:absolute; width:250px; height:250px; right:-88px; top:-118px; border-radius:999px; background:radial-gradient(circle,rgba(79,140,255,.15),transparent 66%); pointer-events:none; }
.pb-hero-grid { position:relative; z-index:1; display:grid; grid-template-columns:minmax(0,1fr) 305px; gap:2rem; align-items:stretch; }
.pb-eyebrow { display:inline-flex; align-items:center; gap:.48rem; color:var(--pb-blue); font-size:.68rem; font-weight:790; letter-spacing:.125em; text-transform:uppercase; }
.pb-eyebrow-dot { width:6px; height:6px; border-radius:50%; background:var(--pb-cyan); box-shadow:0 0 0 5px rgba(39,211,194,.09); }
.pb-hero h1 { margin:.52rem 0 .48rem; font-size:clamp(2rem,3.5vw,2.85rem); line-height:1.02; letter-spacing:-.052em; color:var(--text-color); }
.pb-hero-copy { max-width:790px; margin:0; font-size:.90rem; line-height:1.72; color:color-mix(in srgb,var(--text-color) 62%,transparent); }
.pb-chip-row { display:flex; flex-wrap:wrap; gap:.48rem; margin-top:1.08rem; }
.pb-chip { display:inline-flex; align-items:center; gap:.38rem; padding:.36rem .62rem; border-radius:999px; border:1px solid var(--pb-line); background:color-mix(in srgb,var(--background-color) 54%,transparent); font-size:.70rem; font-weight:630; color:color-mix(in srgb,var(--text-color) 72%,transparent); }
.pb-chip-dot { width:6px; height:6px; border-radius:50%; background:var(--pb-blue); }
.pb-hero-panel { display:flex; flex-direction:column; justify-content:space-between; min-height:142px; padding:1rem 1.05rem; border-radius:16px; border:1px solid var(--pb-line); background:color-mix(in srgb,var(--background-color) 56%,transparent); backdrop-filter:blur(16px); }
.pb-hero-panel-head { display:flex; align-items:center; justify-content:space-between; gap:.8rem; font-size:.66rem; font-weight:720; letter-spacing:.09em; text-transform:uppercase; color:var(--pb-muted); }
.pb-hero-panel-head span:last-child { color:var(--pb-cyan); }
.pb-hero-panel-value { margin:.72rem 0 .1rem; font-size:1.55rem; font-weight:730; letter-spacing:-.04em; color:var(--text-color); }
.pb-hero-panel-sub { font-size:.70rem; line-height:1.5; color:var(--pb-muted); }
.pb-mini-bars { display:flex; align-items:end; gap:5px; height:27px; margin-top:.8rem; }
.pb-mini-bars i { display:block; flex:1; border-radius:3px 3px 1px 1px; background:linear-gradient(to top,rgba(79,140,255,.32),rgba(39,211,194,.75)); }
.pb-mini-bars i:nth-child(1) { height:34%; }
.pb-mini-bars i:nth-child(2) { height:52%; }
.pb-mini-bars i:nth-child(3) { height:43%; }
.pb-mini-bars i:nth-child(4) { height:73%; }
.pb-mini-bars i:nth-child(5) { height:60%; }
.pb-mini-bars i:nth-child(6) { height:88%; }
.pb-mini-bars i:nth-child(7) { height:68%; }
.pb-mini-bars i:nth-child(8) { height:100%; }
.pb-mini-bars i:nth-child(9) { height:82%; }
.pb-mini-bars i:nth-child(10) { height:92%; }

/* ---------- Section headers ---------- */
.pb-section-head { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin:1.72rem 0 .76rem; }
.pb-section-kicker { display:inline-flex; align-items:center; gap:.42rem; font-size:.66rem; font-weight:780; text-transform:uppercase; letter-spacing:.115em; color:var(--pb-blue); margin-bottom:.23rem; }
.pb-section-kicker::after { content:""; width:30px; height:1px; background:linear-gradient(90deg,rgba(79,140,255,.55),transparent); }
.pb-section-title { font-size:1.16rem; font-weight:735; letter-spacing:-.025em; color:var(--text-color); }
.pb-section-desc { margin-top:.23rem; max-width:760px; font-size:.78rem; line-height:1.55; color:color-mix(in srgb,var(--text-color) 52%,transparent); }

/* ---------- Cards / metrics ---------- */
[data-testid="stMetric"] {
    position: relative;
    overflow: hidden;
    min-height: 116px;
    padding: 1.02rem 1.08rem;
    border: 1px solid var(--pb-line);
    border-radius: var(--pb-radius-lg);
    background: linear-gradient(145deg,rgba(79,140,255,.042),transparent 52%), color-mix(in srgb,var(--secondary-background-color) 68%,transparent);
    box-shadow:0 12px 34px rgba(0,0,0,.035), inset 0 1px rgba(255,255,255,.02);
    transition:transform .18s ease,border-color .18s ease,background .18s ease;
}
[data-testid="stMetric"]::before { content:""; position:absolute; top:0; left:18px; right:18px; height:1px; background:linear-gradient(90deg,transparent,rgba(79,140,255,.34),transparent); }
[data-testid="stMetric"]:hover { transform:translateY(-2px); border-color:color-mix(in srgb,var(--pb-blue) 24%,var(--pb-line)); background:linear-gradient(145deg,rgba(79,140,255,.065),transparent 55%),color-mix(in srgb,var(--secondary-background-color) 72%,transparent); }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) [data-testid="stMetric"]::before { background:linear-gradient(90deg,transparent,rgba(39,211,194,.38),transparent); }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) [data-testid="stMetric"]::before { background:linear-gradient(90deg,transparent,rgba(139,124,246,.38),transparent); }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4) [data-testid="stMetric"]::before { background:linear-gradient(90deg,transparent,rgba(240,180,95,.36),transparent); }
[data-testid="stMetricLabel"] { font-size:.72rem; font-weight:650; color:color-mix(in srgb,var(--text-color) 50%,transparent); }
[data-testid="stMetricValue"] { margin-top:.27rem; font-size:1.75rem; font-weight:690; letter-spacing:-.04em; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:var(--pb-radius-lg) !important; border-color:var(--pb-line) !important; background:linear-gradient(180deg,rgba(255,255,255,.012),transparent 7rem),color-mix(in srgb,var(--secondary-background-color) 56%,transparent); box-shadow:0 14px 40px rgba(0,0,0,.035),inset 0 1px rgba(255,255,255,.015); }
[data-testid="stVerticalBlockBorderWrapper"] > div { padding:.2rem; }
.st-key-offer_card [data-testid="stVerticalBlockBorderWrapper"] { background:linear-gradient(135deg,rgba(79,140,255,.035),transparent 36%),color-mix(in srgb,var(--secondary-background-color) 57%,transparent); }
.st-key-run_card [data-testid="stVerticalBlockBorderWrapper"] { border-color:color-mix(in srgb,var(--pb-blue) 16%,var(--pb-line)) !important; background:linear-gradient(100deg,rgba(79,140,255,.065),rgba(39,211,194,.018) 46%,transparent 74%),color-mix(in srgb,var(--secondary-background-color) 62%,transparent); }
.pb-card-heading { display:flex; align-items:center; justify-content:space-between; gap:1rem; margin-bottom:.1rem; }
.pb-card-title { font-size:.88rem; font-weight:710; color:var(--text-color); }
.pb-card-meta { padding:.28rem .5rem; border-radius:999px; border:1px solid var(--pb-line); font-size:.64rem; color:var(--pb-muted); }
.pb-note { display:flex; gap:.75rem; align-items:flex-start; padding:.88rem .95rem; margin:.78rem 0 .9rem; border-radius:13px; border:1px solid rgba(79,140,255,.15); background:linear-gradient(90deg,rgba(79,140,255,.055),rgba(39,211,194,.018)); }
.pb-note-mark { flex:0 0 auto; width:24px; height:24px; border-radius:8px; display:grid; place-items:center; color:var(--pb-blue); background:rgba(79,140,255,.10); font-size:.72rem; font-weight:800; }
.pb-note-copy { font-size:.77rem; line-height:1.62; color:color-mix(in srgb,var(--text-color) 57%,transparent); }
.pb-note-copy strong { color:color-mix(in srgb,var(--text-color) 84%,transparent); font-weight:700; }
.pb-action-copy { padding:.16rem 0 .3rem; }
.pb-action-title { font-size:.91rem; font-weight:715; color:var(--text-color); }
.pb-action-desc { margin-top:.22rem; font-size:.73rem; line-height:1.48; color:color-mix(in srgb,var(--text-color) 48%,transparent); }
.pb-result-banner { display:flex; justify-content:space-between; gap:1rem; align-items:center; padding:.82rem .92rem; margin:.3rem 0 .78rem; border-radius:13px; background:linear-gradient(90deg,rgba(39,211,194,.065),rgba(79,140,255,.045)); border:1px solid rgba(39,211,194,.14); font-size:.74rem; color:color-mix(in srgb,var(--text-color) 56%,transparent); }
.pb-result-banner strong { color:var(--text-color); }

/* ---------- Buttons ---------- */
.stButton > button,
.stDownloadButton > button { min-height:2.72rem; border-radius:11px; border-color:var(--pb-line-strong); font-weight:680; letter-spacing:-.008em; transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease,background .16s ease; }
.stButton > button[kind="primary"] { border:1px solid rgba(117,171,255,.20); color:white; background:linear-gradient(100deg,#356fe6 0%,#4f8cff 62%,#34aeb1 118%); box-shadow:0 10px 24px rgba(43,105,224,.18),inset 0 1px rgba(255,255,255,.12); }
.stButton > button:hover,
.stDownloadButton > button:hover { transform:translateY(-1px); border-color:color-mix(in srgb,var(--pb-blue) 42%,var(--pb-line)); }
.stButton > button[kind="primary"]:hover { box-shadow:0 13px 28px rgba(43,105,224,.24),inset 0 1px rgba(255,255,255,.16); }

/* ---------- Data / charts / tabs ---------- */
[data-testid="stDataFrame"],
[data-testid="stDataEditor"] { overflow:hidden; border:1px solid var(--pb-line); border-radius:13px; background:color-mix(in srgb,var(--background-color) 45%,transparent); }
[data-testid="stDataEditor"] [role="grid"],
[data-testid="stDataFrame"] [role="grid"] { border:0 !important; }
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap:.35rem; padding:.26rem; border:1px solid var(--pb-line); border-radius:12px; background:color-mix(in srgb,var(--secondary-background-color) 50%,transparent); }
[data-testid="stTabs"] [data-baseweb="tab-highlight"] { display:none; }
[data-testid="stTabs"] [data-baseweb="tab"] { height:2.45rem; padding:0 .82rem; border-radius:9px; font-size:.76rem; font-weight:640; color:var(--pb-muted); }
[data-testid="stTabs"] [aria-selected="true"] { color:var(--text-color) !important; background:color-mix(in srgb,var(--background-color) 74%,transparent) !important; box-shadow:0 4px 14px rgba(0,0,0,.04); }
[data-testid="stExpander"] { overflow:hidden; border-radius:12px; border-color:var(--pb-line); }
[data-testid="stAltairChart"] { border-radius:12px; overflow:hidden; }
hr { border-color:var(--pb-line) !important; }
* { scrollbar-width:thin; scrollbar-color:color-mix(in srgb,var(--text-color) 18%,transparent) transparent; }
*::-webkit-scrollbar { width:8px; height:8px; }
*::-webkit-scrollbar-thumb { border:2px solid transparent; border-radius:999px; background:color-mix(in srgb,var(--text-color) 18%,transparent); background-clip:padding-box; }

/* ---------- Motion ---------- */
@keyframes pbRise { from { opacity:0; transform:translateY(7px); } to { opacity:1; transform:translateY(0); } }
.pb-hero,
.pb-section-head,
[data-testid="stMetric"] { animation:pbRise .32s ease both; }
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration:.01ms !important; animation-iteration-count:1 !important; transition-duration:.01ms !important; scroll-behavior:auto !important; }
}
@media (max-width: 1100px) {
    .pb-hero-grid { grid-template-columns:1fr; }
    .pb-hero-panel { display:none; }
}
@media (max-width: 900px) {
    [data-testid="stAppViewBlockContainer"] { padding:.85rem 1rem 3rem; }
    section[data-testid="stSidebar"] { width:300px !important; min-width:300px !important; }
    .pb-hero { padding:1.35rem 1.2rem 1.22rem; border-radius:18px; }
    .pb-section-head { align-items:flex-start; flex-direction:column; }
    .pb-result-banner { align-items:flex-start; flex-direction:column; }
}
</style>
"""

st.markdown(APP_CSS, unsafe_allow_html=True)


def section_header(kicker: str, title: str, description: str) -> None:
    st.markdown(
        f"""
        <div class="pb-section-head">
            <div>
                <div class="pb-section-kicker">{kicker}</div>
                <div class="pb-section-title">{title}</div>
                <div class="pb-section-desc">{description}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def chart_style(chart: alt.Chart) -> alt.Chart:
    return (
        chart.properties(height=292)
        .configure(background="transparent")
        .configure_view(strokeWidth=0)
        .configure_axis(
            labelFont="Inter",
            titleFont="Inter",
            labelFontSize=10,
            titleFontSize=10,
            labelColor="#8793a5",
            titleColor="#8793a5",
            labelPadding=8,
            titlePadding=12,
            gridColor="#64748b",
            gridOpacity=0.11,
            domain=False,
            ticks=False,
        )
        .configure_legend(
            labelFont="Inter",
            titleFont="Inter",
            labelFontSize=10,
            titleFontSize=10,
            labelColor="#8793a5",
            titleColor="#8793a5",
            orient="top",
            padding=4,
        )
    )


base = load_scenario(ROOT / "data" / "sample_market.json")
source_label = {
    "synthetic": "仿真构造数据",
    "course": "课程材料",
    "platform": "老师仿真平台",
    "public": "公开市场数据",
    "unknown": "来源未标记",
}.get(base.data_source, base.data_source)

with st.sidebar:
    st.markdown(
        """
        <div class="pb-side-brand">
            <div class="pb-side-logo">
                <svg viewBox="0 0 32 32" width="21" height="21" aria-hidden="true">
                    <path d="M5.5 21.5L11 16l4 3.5L22.5 10l4 3" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M21 7.5h6v6" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" opacity=".72"/>
                </svg>
            </div>
            <div>
                <div class="pb-side-title">PowerBid Lab</div>
                <div class="pb-side-subtitle">BIDDING CONTROL CENTER</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True, key="sidebar_market"):
        st.markdown(
            """
            <div class="pb-side-group-head">
                <div class="pb-side-group-title"><span class="pb-side-index">01</span>市场设置</div>
                <span class="pb-side-group-meta">MARKET</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        demand_mw = st.number_input("市场负荷 / MW", min_value=0.0, value=base.demand_mw, step=10.0)
        interval_hours = st.number_input("结算时段 / h", min_value=0.25, value=base.interval_hours, step=0.25)
        target_unit_id = st.selectbox("目标机组", [offer.unit_id for offer in base.offers], index=0)
        engine_name = st.selectbox("出清引擎", ["内置统一出清价", "PyPSA"])
        decision_mode = st.selectbox("决策模式", ["单场景利润最大化", "不确定性 / 风险分析"])

    with st.container(border=True, key="sidebar_bid"):
        st.markdown(
            """
            <div class="pb-side-group-head">
                <div class="pb-side-group-title"><span class="pb-side-index">02</span>报价搜索</div>
                <span class="pb-side-group-meta">SEARCH</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        bid_start = st.number_input("最低报价", min_value=0.0, value=180.0, step=10.0)
        bid_stop = st.number_input("最高报价", min_value=0.0, value=400.0, step=10.0)
        bid_step = st.number_input("报价步长", min_value=0.1, value=10.0, step=1.0)

    if decision_mode == "不确定性 / 风险分析":
        with st.container(border=True, key="sidebar_risk"):
            st.markdown(
                """
                <div class="pb-side-group-head">
                    <div class="pb-side-group-title"><span class="pb-side-index">03</span>风险控制</div>
                    <span class="pb-side-group-meta">RISK</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            demand_uncertainty = st.slider("负荷上下波动", 0, 40, 15, 5) / 100.0
            competitor_uncertainty = st.slider("竞争报价上下波动", 0, 40, 15, 5) / 100.0
            risk_aversion = st.slider(
                "风险厌恶程度", 0.0, 1.0, 0.35, 0.05,
                help="0 = 只看平均利润；1 = 更重视最差一段市场情形。",
            )
            tail_fraction = st.slider(
                "下行情景比例", 0.10, 1.00, 0.25, 0.05,
                help="用于计算最差一部分情景的平均利润。",
            )

    st.markdown(
        f"""
        <div class="pb-side-summary">
            <div class="pb-side-summary-head">
                <span>当前配置</span>
                <span class="pb-side-ready"><span class="pb-live-dot"></span>READY</span>
            </div>
            <div class="pb-side-summary-grid">
                <div class="pb-side-summary-item"><span>目标机组</span><strong>{target_unit_id}</strong></div>
                <div class="pb-side-summary-item"><span>市场负荷</span><strong>{demand_mw:,.0f} MW</strong></div>
                <div class="pb-side-summary-item"><span>报价区间</span><strong>{bid_start:g} – {bid_stop:g}</strong></div>
                <div class="pb-side-summary-item"><span>报价步长</span><strong>{bid_step:g}</strong></div>
            </div>
        </div>
        <div class="pb-side-footnote">{engine_name} · {source_label}</div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    f"""
    <div class="pb-topbar">
        <div class="pb-breadcrumb"><span>PowerBid</span><span>/</span><strong>报价决策工作台</strong></div>
        <div class="pb-top-status"><span class="pb-live-dot"></span>模型服务正常 · 实时计算</div>
    </div>
    <section class="pb-hero">
        <div class="pb-hero-grid">
            <div>
                <div class="pb-eyebrow"><span class="pb-eyebrow-dot"></span>Power Market Decision Lab</div>
                <h1>发电侧报价决策控制台</h1>
                <p class="pb-hero-copy">
                    将候选报价送入统一出清环境，以中标电量、出清价格和利润反馈寻找更稳健的报价策略。
                    每一次推荐都保留数据来源、出清过程与风险情景，便于复盘和教学研讨。
                </p>
                <div class="pb-chip-row">
                    <span class="pb-chip"><span class="pb-chip-dot"></span>{engine_name}</span>
                    <span class="pb-chip">{decision_mode}</span>
                    <span class="pb-chip">数据源 · {source_label}</span>
                </div>
            </div>
            <aside class="pb-hero-panel">
                <div class="pb-hero-panel-head"><span>Current workspace</span><span>READY</span></div>
                <div>
                    <div class="pb-hero-panel-value">{target_unit_id} · {demand_mw:,.0f} MW</div>
                    <div class="pb-hero-panel-sub">候选报价 {bid_start:g}–{bid_stop:g} · 步长 {bid_step:g} · {interval_hours:g} h</div>
                    <div class="pb-mini-bars"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
                </div>
            </aside>
        </div>
    </section>
    """,
    unsafe_allow_html=True,
)

summary_cols = st.columns(4)
summary_cols[0].metric("市场负荷", f"{demand_mw:,.0f} MW", help="当前场景总负荷")
summary_cols[1].metric("目标机组", target_unit_id, help="本轮需要优化报价的机组")
summary_cols[2].metric(
    "候选区间",
    f"{bid_start:g} – {bid_stop:g}",
    help=f"按 {bid_step:g} 的步长搜索候选报价",
)
summary_cols[3].metric("结算时段", f"{interval_hours:g} h", help="用于收益与成本结算")

section_header(
    "01 · Market Inputs",
    "机组与报价数据",
    "直接编辑各机组的申报容量、当前报价和真实边际成本。目标机组的报价会在运行时被候选价格逐一替换。",
)

source_df = pd.DataFrame(
    [
        {
            "unit_id": offer.unit_id,
            "quantity_mw": offer.quantity_mw,
            "bid_price": offer.bid_price,
            "marginal_cost": offer.marginal_cost,
        }
        for offer in base.offers
    ]
)

with st.container(border=True, key="offer_card"):
    meta_left, meta_right = st.columns([4, 1])
    with meta_left:
        st.markdown(
            """
            <div class="pb-card-heading">
                <div class="pb-card-title">机组申报参数</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("修改仅作用于当前分析，不覆盖原始样例文件。")
    with meta_right:
        st.markdown(
            f'<div style="text-align:right"><span class="pb-card-meta">{len(source_df)} UNIT · {source_label}</span></div>',
            unsafe_allow_html=True,
        )

    edited_df = st.data_editor(
        source_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="offer_editor",
        column_config={
            "unit_id": st.column_config.TextColumn("机组", help="机组唯一标识"),
            "quantity_mw": st.column_config.NumberColumn(
                "申报容量 / MW", min_value=0.0, format="%.2f"
            ),
            "bid_price": st.column_config.NumberColumn(
                "当前报价", min_value=0.0, format="%.2f"
            ),
            "marginal_cost": st.column_config.NumberColumn(
                "真实边际成本", min_value=0.0, format="%.2f"
            ),
        },
    )

st.markdown(
    """
    <div class="pb-note">
        <div class="pb-note-mark">i</div>
        <div class="pb-note-copy">
            <strong>计算逻辑：</strong>单场景模式寻找当前市场输入下利润最高的报价；风险模式会同时改变负荷和竞争者报价，
            用多种压力情景检查同一报价是否仍然稳健。当前压力情景属于敏感性分析，不代表真实市场预测。
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

section_header(
    "02 · Decision Run",
    "运行报价优化",
    "确认左侧控制参数和机组数据后开始计算。所有候选报价都会经过同一套出清与结算流程。",
)

with st.container(border=True, key="run_card"):
    action_left, action_right = st.columns([3.4, 1.6], vertical_alignment="center")
    with action_left:
        st.markdown(
            f"""
            <div class="pb-action-copy">
                <div class="pb-action-title"><span class="pb-live-dot"></span>决策引擎已就绪</div>
                <div class="pb-action-desc">
                    {decision_mode} · {engine_name} · 候选 {bid_start:g}–{bid_stop:g} / 步长 {bid_step:g}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with action_right:
        run = st.button("开始优化报价", type="primary", use_container_width=True)

if run:
    try:
        with st.spinner("正在完成候选报价出清与收益评估…"):
            offers = tuple(
                Offer(
                    unit_id=str(row.unit_id),
                    quantity_mw=float(row.quantity_mw),
                    bid_price=float(row.bid_price),
                    marginal_cost=float(row.marginal_cost),
                )
                for row in edited_df.itertuples(index=False)
            )
            scenario = MarketScenario(
                name="interactive-demo",
                demand_mw=float(demand_mw),
                interval_hours=float(interval_hours),
                target_unit_id=target_unit_id,
                offers=offers,
                description="Interactive teaching scenario built in the Streamlit UI.",
                data_source="synthetic",
            )
            engine = PyPSAClearingEngine() if engine_name == "PyPSA" else UniformPriceClearingEngine()
            candidates = price_grid(float(bid_start), float(bid_stop), float(bid_step))

            if decision_mode == "单场景利润最大化":
                result = GridSearchBidOptimizer(engine).optimize(scenario, candidates)
            else:
                demand_multipliers = (1.0 - demand_uncertainty, 1.0, 1.0 + demand_uncertainty)
                competitor_multipliers = (1.0 - competitor_uncertainty, 1.0, 1.0 + competitor_uncertainty)
                stress_cases = build_stress_cases(
                    scenario,
                    demand_multipliers=demand_multipliers,
                    competitor_bid_multipliers=competitor_multipliers,
                )
                result = RiskAwareBidOptimizer(
                    engine,
                    risk_aversion=risk_aversion,
                    tail_fraction=tail_fraction,
                    min_feasible_probability=1.0,
                ).optimize(stress_cases, candidates)
    except Exception as exc:
        st.error(f"本轮优化没有完成：{exc}")
    else:
        section_header(
            "03 · Decision Output",
            "报价决策结果",
            "先看推荐结果，再下钻到收益曲线、风险区间和全部试算明细。",
        )

        if decision_mode == "单场景利润最大化":
            best = result.best
            result_cols = st.columns(4)
            result_cols[0].metric("推荐报价", f"{best.bid_price:.2f}")
            result_cols[1].metric("出清价格", "—" if best.clearing_price is None else f"{best.clearing_price:.2f}")
            result_cols[2].metric("预计中标", f"{best.accepted_mw:.2f} MW")
            result_cols[3].metric("预计利润", f"{best.profit:,.2f}")

            trials_df = pd.DataFrame(
                [
                    {
                        "报价": item.bid_price,
                        "出清价格": item.clearing_price,
                        "中标电量MW": item.accepted_mw,
                        "收入": item.revenue,
                        "变动成本": item.variable_cost,
                        "利润": item.profit,
                        "可行": item.feasible,
                    }
                    for item in result.trials
                ]
            )

            st.markdown(
                f"""
                <div class="pb-result-banner">
                    <span><strong>策略摘要</strong> · 当前最优报价为 {best.bid_price:.2f}</span>
                    <span>{len(trials_df)} 个候选报价已完成试算</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            overview_tab, detail_tab = st.tabs(["策略概览", "全部试算"])
            with overview_tab:
                left, right = st.columns(2)
                with left:
                    with st.container(border=True):
                        st.markdown("**报价 — 利润**")
                        st.caption("观察报价变化如何影响目标机组利润。")
                        profit_area = (
                            alt.Chart(trials_df)
                            .mark_area(line={"color": "#3b82f6", "strokeWidth": 2.4}, color="#3b82f6", opacity=0.16)
                            .encode(
                                x=alt.X("报价:Q", title="报价"),
                                y=alt.Y("利润:Q", title="利润", scale=alt.Scale(zero=False)),
                                tooltip=[alt.Tooltip("报价:Q", format=".2f"), alt.Tooltip("利润:Q", format=",.2f")],
                            )
                        )
                        best_rule = alt.Chart(pd.DataFrame({"报价": [best.bid_price]})).mark_rule(color="#14b8a6", strokeDash=[6, 5], strokeWidth=1.5).encode(x="报价:Q")
                        st.altair_chart(chart_style(alt.layer(profit_area, best_rule)), use_container_width=True)

                with right:
                    with st.container(border=True):
                        st.markdown("**报价 — 中标电量**")
                        st.caption("用于识别报价提高后可能出现的中标量拐点。")
                        quantity_chart = (
                            alt.Chart(trials_df)
                            .mark_line(point=True, strokeWidth=2.4, color="#14b8a6")
                            .encode(
                                x=alt.X("报价:Q", title="报价"),
                                y=alt.Y("中标电量MW:Q", title="中标电量 / MW"),
                                tooltip=[alt.Tooltip("报价:Q", format=".2f"), alt.Tooltip("中标电量MW:Q", format=".2f")],
                            )
                        )
                        st.altair_chart(chart_style(quantity_chart), use_container_width=True)

            with detail_tab:
                with st.container(border=True):
                    st.dataframe(
                        trials_df.style.format(
                            {
                                "报价": "{:.2f}",
                                "出清价格": "{:.2f}",
                                "中标电量MW": "{:.2f}",
                                "收入": "{:,.2f}",
                                "变动成本": "{:,.2f}",
                                "利润": "{:,.2f}",
                            },
                            na_rep="—",
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.download_button(
                        "导出试算结果 CSV",
                        trials_df.to_csv(index=False).encode("utf-8-sig"),
                        file_name="powerbid_single_scenario.csv",
                        mime="text/csv",
                    )
        else:
            best = result.best
            result_cols = st.columns(4)
            result_cols[0].metric("推荐报价", f"{best.bid_price:.2f}")
            result_cols[1].metric("期望利润", f"{best.expected_profit:,.2f}")
            result_cols[2].metric("下行情景利润", f"{best.downside_profit:,.2f}")
            result_cols[3].metric("最差情景利润", f"{best.worst_profit:,.2f}")

            risk_df = pd.DataFrame(
                [
                    {
                        "报价": item.bid_price,
                        "期望利润": item.expected_profit,
                        "下行情景利润": item.downside_profit,
                        "最差情景利润": item.worst_profit,
                        "预计中标MW": item.expected_accepted_mw,
                        "可行概率": item.feasible_probability,
                        "风险得分": item.score,
                    }
                    for item in result.trials
                ]
            )
            outcome_df = pd.DataFrame(
                [
                    {
                        "情景": item.name,
                        "概率权重": item.probability,
                        "出清价格": item.clearing_price,
                        "中标MW": item.accepted_mw,
                        "利润": item.profit,
                        "可行": item.feasible,
                    }
                    for item in best.outcomes
                ]
            )

            st.markdown(
                f"""
                <div class="pb-result-banner">
                    <span><strong>风险摘要</strong> · 风险得分 {best.score:,.2f} · 可行概率 {best.feasible_probability:.0%}</span>
                    <span>预计中标 {best.expected_accepted_mw:.2f} MW</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            risk_tab, scenario_tab, all_tab = st.tabs(["风险曲线", "压力情景", "全部候选"])
            with risk_tab:
                left, right = st.columns([3, 2])
                risk_long = risk_df.melt(
                    id_vars=["报价"],
                    value_vars=["期望利润", "下行情景利润", "最差情景利润"],
                    var_name="指标",
                    value_name="利润",
                )
                with left:
                    with st.container(border=True):
                        st.markdown("**收益 / 下行风险曲线**")
                        st.caption("同时看平均收益和坏情景下的利润表现。")
                        risk_chart = (
                            alt.Chart(risk_long)
                            .mark_line(point=True, strokeWidth=2.2)
                            .encode(
                                x=alt.X("报价:Q", title="报价"),
                                y=alt.Y("利润:Q", title="利润", scale=alt.Scale(zero=False)),
                                color=alt.Color("指标:N", title=None, scale=alt.Scale(range=["#3b82f6", "#8b5cf6", "#ef4444"])),
                                tooltip=[alt.Tooltip("报价:Q", format=".2f"), alt.Tooltip("指标:N"), alt.Tooltip("利润:Q", format=",.2f")],
                            )
                        )
                        st.altair_chart(chart_style(risk_chart), use_container_width=True)

                with right:
                    with st.container(border=True):
                        st.markdown("**风险得分**")
                        st.caption("综合期望利润与下行情景利润后的决策指标。")
                        score_chart = (
                            alt.Chart(risk_df)
                            .mark_area(line={"color": "#14b8a6", "strokeWidth": 2.4}, color="#14b8a6", opacity=0.16)
                            .encode(
                                x=alt.X("报价:Q", title="报价"),
                                y=alt.Y("风险得分:Q", title="风险得分", scale=alt.Scale(zero=False)),
                                tooltip=[alt.Tooltip("报价:Q", format=".2f"), alt.Tooltip("风险得分:Q", format=",.2f")],
                            )
                        )
                        st.altair_chart(chart_style(score_chart), use_container_width=True)

            with scenario_tab:
                with st.container(border=True):
                    st.markdown("**推荐报价在各压力情景下的表现**")
                    st.caption("逐个检查推荐报价在不同负荷和竞争报价状态下的出清结果。")
                    st.dataframe(
                        outcome_df.style.format(
                            {"概率权重": "{:.1%}", "出清价格": "{:.2f}", "中标MW": "{:.2f}", "利润": "{:,.2f}"},
                            na_rep="—",
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

            with all_tab:
                with st.container(border=True):
                    st.dataframe(
                        risk_df.style.format(
                            {
                                "报价": "{:.2f}",
                                "期望利润": "{:,.2f}",
                                "下行情景利润": "{:,.2f}",
                                "最差情景利润": "{:,.2f}",
                                "预计中标MW": "{:.2f}",
                                "可行概率": "{:.1%}",
                                "风险得分": "{:,.2f}",
                            }
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.download_button(
                        "导出风险分析 CSV",
                        risk_df.to_csv(index=False).encode("utf-8-sig"),
                        file_name="powerbid_risk_analysis.csv",
                        mime="text/csv",
                    )

st.markdown(
    """
    <div style="height:1.6rem"></div>
    <div style="text-align:center;font-size:.72rem;opacity:.42;padding:.7rem 0 1.2rem;">
        PowerBid Lab · Transparent bidding decisions for teaching and research
    </div>
    """,
    unsafe_allow_html=True,
)
