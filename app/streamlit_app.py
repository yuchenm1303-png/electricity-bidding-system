from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
APP_DIR = Path(__file__).resolve().parent
for module_path in (SRC, APP_DIR):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

from design_system import APP_CSS  # noqa: E402
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
        chart.properties(height=305)
        .configure(background="transparent")
        .configure_view(strokeWidth=0)
        .configure_axis(
            labelFont="Inter",
            titleFont="Inter",
            labelFontSize=10,
            titleFontSize=10,
            labelColor="#9caac0",
            titleColor="#9caac0",
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
            labelColor="#9caac0",
            titleColor="#9caac0",
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
                <div class="pb-side-subtitle">MARKET DECISION STUDIO</div>
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
        interval_hours = st.number_input(
            "结算时段 / h", min_value=0.25, value=base.interval_hours, step=0.25
        )
        target_unit_id = st.selectbox("目标机组", [offer.unit_id for offer in base.offers], index=0)
        engine_name = st.selectbox("出清引擎", ["内置统一出清价", "PyPSA"])
        decision_mode = st.selectbox("决策模式", ["单场景利润最大化", "不确定性 / 风险分析"])

    with st.container(border=True, key="sidebar_bid"):
        st.markdown(
            """
            <div class="pb-side-group-head">
                <div class="pb-side-group-title"><span class="pb-side-index">02</span>报价区间</div>
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
        <div class="pb-breadcrumb">
            <span>POWERBID LAB</span><span class="pb-crumb-separator">/</span>
            <strong>报价决策工作台</strong>
        </div>
        <div class="pb-top-status"><span class="pb-live-dot"></span>教学模拟环境 · 就绪</div>
    </div>
    <section class="pb-hero" aria-label="电力报价决策概览">
        <div class="pb-hero-grid">
            <div>
                <div class="pb-eyebrow"><span class="pb-eyebrow-dot"></span>Decision intelligence / Power market</div>
                <h1>把复杂市场，<br><em>变成清晰决策。</em></h1>
                <p class="pb-hero-copy">
                    从机组成本、申报容量到市场出清与风险评估，所有报价选择都有迹可循。
                    用清晰的模拟结果比较方案，不靠猜测做决定。
                </p>
                <div class="pb-chip-row">
                    <span class="pb-chip"><span class="pb-chip-dot"></span>{engine_name}</span>
                    <span class="pb-chip">{decision_mode}</span>
                    <span class="pb-chip">数据来源 / {source_label}</span>
                </div>
            </div>
            <aside class="pb-hero-panel">
                <div class="pb-hero-panel-head"><span>Active scenario</span><span>SIMULATION</span></div>
                <div class="pb-hero-visual">
                    <div class="pb-orbit" aria-hidden="true">
                        <span class="pb-orbit-dot"></span>
                        <span class="pb-orbit-core">↗</span>
                    </div>
                    <div>
                        <div class="pb-hero-panel-value">{target_unit_id}</div>
                        <div class="pb-hero-panel-sub">目标机组<br>负荷 {demand_mw:,.0f} MW</div>
                    </div>
                </div>
                <div class="pb-panel-divider"></div>
                <div class="pb-panel-foot">
                    <span>报价 {bid_start:g}–{bid_stop:g} / {interval_hours:g} h</span>
                    <strong>步长 {bid_step:g}</strong>
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
    "01 / MARKET INPUTS",
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
            (
                f'<div style="text-align:right"><span class="pb-card-meta">'
                f'{len(source_df)} UNIT · {source_label}</span></div>'
            ),
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
        <div class="pb-note-mark">◎</div>
        <div class="pb-note-copy">
            <strong>计算逻辑：</strong>单场景模式寻找当前市场输入下利润最高的报价；风险模式会同时改变负荷和竞争者报价，
            用多种压力情景检查同一报价是否仍然稳健。当前压力情景属于敏感性分析，不代表真实市场预测。
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

section_header(
    "02 / RUN OPTIMIZATION",
    "运行报价优化",
    "确认左侧控制参数和机组数据后开始计算。所有候选报价都会经过同一套出清与结算流程。",
)

valid_range = bid_start <= bid_stop
valid_target = target_unit_id in edited_df["unit_id"].astype(str).tolist()
if not valid_range:
    st.warning("最低报价不能高于最高报价，请调整左侧报价区间。")
if not valid_target:
    st.warning("目标机组不在当前机组表内。请重新添加该机组，或在左侧选择其他目标机组。")

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
        run = st.button(
            "开始优化报价  ↗",
            type="primary",
            use_container_width=True,
            disabled=not (valid_range and valid_target),
        )

current_signature = (
    decision_mode, engine_name, target_unit_id,
    float(demand_mw), float(interval_hours),
    float(bid_start), float(bid_stop), float(bid_step),
    edited_df.to_json(orient="records", force_ascii=False),
    (
        (demand_uncertainty, competitor_uncertainty, risk_aversion, tail_fraction)
        if decision_mode == "不确定性 / 风险分析" else None
    ),
)
saved_report = st.session_state.get("pb_report")

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
                demand_multipliers = (1.0 - demand_uncertainty, 1.0, 1.0 + demand_uncertainty)
                competitor_multipliers = (
                    1.0 - competitor_uncertainty, 1.0, 1.0 + competitor_uncertainty
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
    except Exception as exc:
        saved_report = None
        st.session_state.pop("pb_report", None)
        st.error(f"本轮优化没有完成：{exc}")
    else:
        saved_report = {
            "result": result,
            "mode": decision_mode,
            "signature": current_signature,
        }
        st.session_state["pb_report"] = saved_report

if saved_report is not None:
    result = saved_report["result"]
    report_mode = saved_report["mode"]
    if saved_report["signature"] != current_signature:
        st.info("下方展示的是上一次成功运行的结果。当前参数已变更，请点击「开始优化报价」更新。")

    section_header(
        "03 / STRATEGY REPORT",
        "报价决策结果",
        "先看推荐结果，再下钻到收益曲线、风险区间和全部试算明细。",
    )

    if report_mode == "单场景利润最大化":
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
                            line={"color": "#58dfc7", "strokeWidth": 2.4},
                            color="#58dfc7", opacity=0.16,
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
                        .mark_rule(color="#8aabfa", strokeDash=[6, 5], strokeWidth=1.5)
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
                        .mark_line(point=True, strokeWidth=2.4, color="#8aabfa")
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
                            color=alt.Color(
                                "指标:N",
                                title=None,
                                scale=alt.Scale(range=["#58dfc7", "#b09afc", "#fd8c98"]),
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
                            line={"color": "#8aabfa", "strokeWidth": 2.4},
                            color="#8aabfa", opacity=0.16,
                        )
                        .encode(
                            x=alt.X("报价:Q", title="报价"),
                            y=alt.Y("风险得分:Q", title="风险得分", scale=alt.Scale(zero=False)),
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

else:
    st.markdown(
        """
        <div class="pb-empty">
            <div class="pb-empty-symbol" aria-hidden="true">↗</div>
            <div class="pb-empty-title">准备好探索更优报价了吗？</div>
            <div class="pb-empty-desc">配置市场参数、调整机组申报数据，然后运行决策模型。<br>推荐报价、收益曲线和情景分析将在这里呈现。</div>
            <div class="pb-empty-step">01 设置参数 &nbsp;&nbsp; / &nbsp;&nbsp; 02 运行优化 &nbsp;&nbsp; / &nbsp;&nbsp; 03 解读结果</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <div style="height:1.8rem"></div>
    <div style="text-align:center;font-size:.68rem;opacity:.48;padding:.75rem 0 1.3rem;letter-spacing:.04em">
        POWERBID LAB <span style="margin:0 .7rem">·</span> DECISIONS BACKED BY SIMULATION
        <span style="margin:0 .7rem">·</span> FOR TEACHING &amp; RESEARCH
    </div>
    """,
    unsafe_allow_html=True,
)
