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
    --pb-accent: #3b82f6;
    --pb-accent-2: #14b8a6;
    --pb-violet: #8b5cf6;
    --pb-danger: #ef4444;
    --pb-radius-xl: 22px;
    --pb-radius-lg: 16px;
    --pb-radius-md: 12px;
}

html, body, [class*="css"] {
    font-family: Inter, "SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont,
        "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at 18% -8%, rgba(59, 130, 246, .10), transparent 30rem),
        radial-gradient(circle at 92% 4%, rgba(20, 184, 166, .08), transparent 28rem),
        var(--background-color);
}

[data-testid="stHeader"] {
    background: transparent;
}

[data-testid="stAppViewBlockContainer"] {
    max-width: 1480px;
    padding-top: 2.1rem;
    padding-bottom: 4rem;
}

[data-testid="stSidebar"] {
    background: color-mix(in srgb, var(--secondary-background-color) 92%, transparent);
    border-right: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: .75rem;
}

[data-testid="stSidebar"] .stMarkdown p {
    margin-bottom: .15rem;
}

.pb-side-brand {
    display: flex;
    align-items: center;
    gap: .8rem;
    padding: .35rem .15rem .9rem;
}

.pb-side-logo {
    width: 38px;
    height: 38px;
    border-radius: 12px;
    display: grid;
    place-items: center;
    font-weight: 800;
    color: white;
    background: linear-gradient(145deg, #2563eb, #14b8a6);
    box-shadow: 0 10px 28px rgba(37, 99, 235, .22);
}

.pb-side-title {
    font-size: .95rem;
    font-weight: 760;
    letter-spacing: -.01em;
    color: var(--text-color);
}

.pb-side-subtitle {
    margin-top: .1rem;
    font-size: .73rem;
    color: color-mix(in srgb, var(--text-color) 56%, transparent);
}

.pb-side-section {
    margin: .35rem 0 .15rem;
    font-size: .70rem;
    font-weight: 750;
    letter-spacing: .09em;
    text-transform: uppercase;
    color: color-mix(in srgb, var(--text-color) 48%, transparent);
}

.pb-hero {
    position: relative;
    overflow: hidden;
    border: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
    border-radius: 26px;
    padding: 2.15rem 2.25rem 1.95rem;
    margin-bottom: 1.15rem;
    background:
        linear-gradient(
            125deg,
            rgba(59, 130, 246, .10),
            rgba(20, 184, 166, .045) 48%,
            transparent 75%
        ),
        color-mix(in srgb, var(--secondary-background-color) 78%, transparent);
    box-shadow: 0 20px 60px rgba(15, 23, 42, .06);
}

.pb-hero::after {
    content: "";
    position: absolute;
    width: 260px;
    height: 260px;
    right: -90px;
    top: -120px;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(59, 130, 246, .16), transparent 68%);
    pointer-events: none;
}

.pb-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: .45rem;
    color: var(--pb-accent);
    font-size: .72rem;
    font-weight: 780;
    letter-spacing: .12em;
    text-transform: uppercase;
}

.pb-eyebrow-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--pb-accent-2);
    box-shadow: 0 0 0 5px rgba(20, 184, 166, .10);
}

.pb-hero h1 {
    margin: .55rem 0 .5rem;
    font-size: clamp(2.05rem, 4vw, 3.25rem);
    line-height: 1.02;
    letter-spacing: -.045em;
    color: var(--text-color);
}

.pb-hero-copy {
    max-width: 760px;
    margin: 0;
    font-size: .96rem;
    line-height: 1.75;
    color: color-mix(in srgb, var(--text-color) 65%, transparent);
}

.pb-chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: .55rem;
    margin-top: 1.25rem;
}

.pb-chip {
    display: inline-flex;
    align-items: center;
    gap: .42rem;
    padding: .42rem .68rem;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
    background: color-mix(in srgb, var(--background-color) 70%, transparent);
    font-size: .76rem;
    font-weight: 650;
    color: color-mix(in srgb, var(--text-color) 76%, transparent);
}

.pb-chip-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--pb-accent);
}

.pb-section-head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
    margin: 1.85rem 0 .8rem;
}

.pb-section-kicker {
    font-size: .69rem;
    font-weight: 760;
    text-transform: uppercase;
    letter-spacing: .11em;
    color: var(--pb-accent);
    margin-bottom: .24rem;
}

.pb-section-title {
    font-size: 1.17rem;
    font-weight: 760;
    letter-spacing: -.02em;
    color: var(--text-color);
}

.pb-section-desc {
    margin-top: .2rem;
    max-width: 720px;
    font-size: .81rem;
    line-height: 1.55;
    color: color-mix(in srgb, var(--text-color) 55%, transparent);
}

.pb-meta {
    display: flex;
    flex-wrap: wrap;
    gap: .55rem 1.15rem;
    padding: .88rem 1rem;
    margin: .65rem 0 .9rem;
    border-radius: 14px;
    border: 1px solid color-mix(in srgb, var(--text-color) 9%, transparent);
    background: color-mix(in srgb, var(--secondary-background-color) 70%, transparent);
    color: color-mix(in srgb, var(--text-color) 64%, transparent);
    font-size: .78rem;
}

.pb-meta strong {
    color: var(--text-color);
    font-weight: 700;
}

.pb-note {
    display: flex;
    gap: .75rem;
    align-items: flex-start;
    padding: .95rem 1rem;
    margin: .8rem 0 .95rem;
    border-radius: 14px;
    border: 1px solid rgba(59, 130, 246, .18);
    background: rgba(59, 130, 246, .055);
}

.pb-note-mark {
    flex: 0 0 auto;
    width: 24px;
    height: 24px;
    border-radius: 8px;
    display: grid;
    place-items: center;
    color: var(--pb-accent);
    background: rgba(59, 130, 246, .11);
    font-size: .76rem;
    font-weight: 800;
}

.pb-note-copy {
    font-size: .80rem;
    line-height: 1.62;
    color: color-mix(in srgb, var(--text-color) 63%, transparent);
}

.pb-note-copy strong {
    color: var(--text-color);
}

.pb-action-copy {
    padding: .2rem 0 .4rem;
}

.pb-action-title {
    font-size: .93rem;
    font-weight: 730;
    color: var(--text-color);
}

.pb-action-desc {
    margin-top: .22rem;
    font-size: .76rem;
    line-height: 1.5;
    color: color-mix(in srgb, var(--text-color) 52%, transparent);
}

.pb-result-banner {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: center;
    padding: .9rem 1rem;
    margin: .35rem 0 .8rem;
    border-radius: 14px;
    background: linear-gradient(90deg, rgba(20, 184, 166, .08), rgba(59, 130, 246, .06));
    border: 1px solid rgba(20, 184, 166, .17);
    font-size: .78rem;
    color: color-mix(in srgb, var(--text-color) 62%, transparent);
}

.pb-result-banner strong {
    color: var(--text-color);
}

[data-testid="stMetric"] {
    min-height: 122px;
    padding: 1rem 1.05rem;
    border: 1px solid color-mix(in srgb, var(--text-color) 9%, transparent);
    border-radius: var(--pb-radius-lg);
    background: color-mix(in srgb, var(--secondary-background-color) 72%, transparent);
    box-shadow: 0 10px 34px rgba(15, 23, 42, .035);
}

[data-testid="stMetricLabel"] {
    font-size: .76rem;
    color: color-mix(in srgb, var(--text-color) 55%, transparent);
}

[data-testid="stMetricValue"] {
    letter-spacing: -.025em;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: var(--pb-radius-lg) !important;
    border-color: color-mix(in srgb, var(--text-color) 9%, transparent) !important;
    background: color-mix(in srgb, var(--secondary-background-color) 58%, transparent);
    box-shadow: 0 12px 38px rgba(15, 23, 42, .035);
}

.stButton > button,
.stDownloadButton > button {
    min-height: 2.75rem;
    border-radius: 12px;
    font-weight: 700;
    letter-spacing: -.005em;
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}

.stButton > button[kind="primary"] {
    border: 0;
    color: white;
    background: linear-gradient(100deg, #2563eb, #3b82f6 55%, #0ea5a5);
    box-shadow: 0 10px 26px rgba(37, 99, 235, .18);
}

.stButton > button:hover,
.stDownloadButton > button:hover {
    transform: translateY(-1px);
}

.stButton > button[kind="primary"]:hover {
    box-shadow: 0 14px 32px rgba(37, 99, 235, .24);
}

[data-baseweb="input"] > div,
[data-baseweb="select"] > div {
    border-radius: 11px !important;
}

[data-testid="stDataFrame"],
[data-testid="stDataEditor"] {
    overflow: hidden;
    border-radius: 14px;
}

[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: .35rem;
    border-bottom: 1px solid color-mix(in srgb, var(--text-color) 9%, transparent);
}

[data-testid="stTabs"] [data-baseweb="tab"] {
    height: 2.7rem;
    padding: 0 .9rem;
    border-radius: 10px 10px 0 0;
    font-size: .82rem;
}

[data-testid="stExpander"] {
    border-radius: 13px;
    border-color: color-mix(in srgb, var(--text-color) 9%, transparent);
    overflow: hidden;
}

hr {
    border-color: color-mix(in srgb, var(--text-color) 8%, transparent) !important;
}

@media (max-width: 900px) {
    [data-testid="stAppViewBlockContainer"] {
        padding-top: 1.25rem;
    }
    .pb-hero {
        padding: 1.55rem 1.35rem 1.4rem;
        border-radius: 20px;
    }
    .pb-section-head {
        align-items: flex-start;
        flex-direction: column;
    }
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
        chart.properties(height=300)
        .configure_view(strokeWidth=0)
        .configure_axis(
            labelFontSize=11,
            titleFontSize=11,
            gridOpacity=0.12,
            domainOpacity=0.15,
            tickOpacity=0.15,
        )
        .configure_legend(labelFontSize=11, titleFontSize=11, orient="top")
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
            <div class="pb-side-logo">P</div>
            <div>
                <div class="pb-side-title">PowerBid Lab</div>
                <div class="pb-side-subtitle">Decision Control Center</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="pb-side-section">Market setup</div>', unsafe_allow_html=True)
    demand_mw = st.number_input(
        "市场负荷 / MW", min_value=0.0, value=base.demand_mw, step=10.0
    )
    interval_hours = st.number_input(
        "结算时段 / h", min_value=0.25, value=base.interval_hours, step=0.25
    )
    target_unit_id = st.selectbox(
        "目标机组", [offer.unit_id for offer in base.offers], index=0
    )
    engine_name = st.selectbox("出清引擎", ["内置统一出清价", "PyPSA"])
    decision_mode = st.selectbox("决策模式", ["单场景利润最大化", "不确定性 / 风险分析"])

    st.markdown('<div class="pb-side-section">Bid search</div>', unsafe_allow_html=True)
    bid_start = st.number_input("最低报价", min_value=0.0, value=180.0, step=10.0)
    bid_stop = st.number_input("最高报价", min_value=0.0, value=400.0, step=10.0)
    bid_step = st.number_input("报价步长", min_value=0.1, value=10.0, step=1.0)

    if decision_mode == "不确定性 / 风险分析":
        st.markdown('<div class="pb-side-section">Risk controls</div>', unsafe_allow_html=True)
        demand_uncertainty = st.slider("负荷上下波动", 0, 40, 15, 5) / 100.0
        competitor_uncertainty = st.slider("竞争报价上下波动", 0, 40, 15, 5) / 100.0
        risk_aversion = st.slider(
            "风险厌恶程度",
            0.0,
            1.0,
            0.35,
            0.05,
            help="0 = 只看平均利润；1 = 更重视最差一段市场情形。",
        )
        tail_fraction = st.slider(
            "下行情景比例",
            0.10,
            1.00,
            0.25,
            0.05,
            help="用于计算最差一部分情景的平均利润。",
        )

    st.markdown("---")
    st.caption(f"数据来源 · {source_label}")
    st.caption("PowerBid Lab 0.1 · 教学 / 研讨原型")

st.markdown(
    f"""
    <section class="pb-hero">
        <div class="pb-eyebrow"><span class="pb-eyebrow-dot"></span>Power Market Decision Lab</div>
        <h1>PowerBid Lab</h1>
        <p class="pb-hero-copy">
            面向发电商的报价决策工作台。把候选报价送入出清环境，用中标结果、利润与下行情景
            反推更稳健的报价选择，让每一次推荐都能追溯到具体数据与计算过程。
        </p>
        <div class="pb-chip-row">
            <span class="pb-chip"><span class="pb-chip-dot"></span>{engine_name}</span>
            <span class="pb-chip">{decision_mode}</span>
            <span class="pb-chip">数据 · {source_label}</span>
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

with st.container(border=True):
    meta_left, meta_right = st.columns([4, 1])
    with meta_left:
        st.markdown("**可编辑机组参数**")
        st.caption("修改后不会覆盖原始样例文件，只用于本次分析。")
    with meta_right:
        st.caption(f"{len(source_df)} 台机组 · {source_label}")

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

with st.container(border=True):
    action_left, action_right = st.columns([3, 2])
    with action_left:
        st.markdown(
            f"""
            <div class="pb-action-copy">
                <div class="pb-action-title">{decision_mode}</div>
                <div class="pb-action-desc">
                    {engine_name} · 报价区间 {bid_start:g}–{bid_stop:g} · 步长 {bid_step:g}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with action_right:
        run = st.button("运行报价优化  →", type="primary", use_container_width=True)

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
            engine = (
                PyPSAClearingEngine()
                if engine_name == "PyPSA"
                else UniformPriceClearingEngine()
            )
            candidates = price_grid(float(bid_start), float(bid_stop), float(bid_step))

            if decision_mode == "单场景利润最大化":
                result = GridSearchBidOptimizer(engine).optimize(scenario, candidates)
            else:
                demand_multipliers = (
                    1.0 - demand_uncertainty,
                    1.0,
                    1.0 + demand_uncertainty,
                )
                competitor_multipliers = (
                    1.0 - competitor_uncertainty,
                    1.0,
                    1.0 + competitor_uncertainty,
                )
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
    except Exception as exc:  # UI boundary: show actionable error instead of crashing
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
            result_cols[1].metric(
                "出清价格",
                "—" if best.clearing_price is None else f"{best.clearing_price:.2f}",
            )
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
                            .mark_area(
                                line={"color": "#3b82f6", "strokeWidth": 2.4},
                                color="#3b82f6",
                                opacity=0.16,
                            )
                            .encode(
                                x=alt.X("报价:Q", title="报价"),
                                y=alt.Y("利润:Q", title="利润", scale=alt.Scale(zero=False)),
                                tooltip=[
                                    alt.Tooltip("报价:Q", format=".2f"),
                                    alt.Tooltip("利润:Q", format=",.2f"),
                                ],
                            )
                        )
                        best_rule = (
                            alt.Chart(pd.DataFrame({"报价": [best.bid_price]}))
                            .mark_rule(color="#14b8a6", strokeDash=[6, 5], strokeWidth=1.5)
                            .encode(x="报价:Q")
                        )
                        st.altair_chart(
                            chart_style(alt.layer(profit_area, best_rule)),
                            use_container_width=True,
                        )

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
                                tooltip=[
                                    alt.Tooltip("报价:Q", format=".2f"),
                                    alt.Tooltip("中标电量MW:Q", format=".2f"),
                                ],
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
                    <span><strong>风险摘要</strong> · 风险得分 {best.score:,.2f} ·
                    可行概率 {best.feasible_probability:.0%}</span>
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
                                color=alt.Color(
                                    "指标:N",
                                    title=None,
                                    scale=alt.Scale(range=["#3b82f6", "#8b5cf6", "#ef4444"]),
                                ),
                                tooltip=[
                                    alt.Tooltip("报价:Q", format=".2f"),
                                    alt.Tooltip("指标:N"),
                                    alt.Tooltip("利润:Q", format=",.2f"),
                                ],
                            )
                        )
                        st.altair_chart(chart_style(risk_chart), use_container_width=True)

                with right:
                    with st.container(border=True):
                        st.markdown("**风险得分**")
                        st.caption("综合期望利润与下行情景利润后的决策指标。")
                        score_chart = (
                            alt.Chart(risk_df)
                            .mark_area(
                                line={"color": "#14b8a6", "strokeWidth": 2.4},
                                color="#14b8a6",
                                opacity=0.16,
                            )
                            .encode(
                                x=alt.X("报价:Q", title="报价"),
                                y=alt.Y(
                                    "风险得分:Q",
                                    title="风险得分",
                                    scale=alt.Scale(zero=False),
                                ),
                                tooltip=[
                                    alt.Tooltip("报价:Q", format=".2f"),
                                    alt.Tooltip("风险得分:Q", format=",.2f"),
                                ],
                            )
                        )
                        st.altair_chart(chart_style(score_chart), use_container_width=True)

            with scenario_tab:
                with st.container(border=True):
                    st.markdown("**推荐报价在各压力情景下的表现**")
                    st.caption("逐个检查推荐报价在不同负荷和竞争报价状态下的出清结果。")
                    st.dataframe(
                        outcome_df.style.format(
                            {
                                "概率权重": "{:.1%}",
                                "出清价格": "{:.2f}",
                                "中标MW": "{:.2f}",
                                "利润": "{:,.2f}",
                            },
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
