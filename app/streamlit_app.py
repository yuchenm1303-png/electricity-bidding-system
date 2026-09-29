from __future__ import annotations

import sys
from pathlib import Path

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

st.set_page_config(page_title="PowerBid Lab", page_icon="⚡", layout="wide")

st.title("PowerBid Lab")
st.caption("发电商报价决策教学原型 · 报价不是拍脑袋，而是由数据、出清与收益反馈共同决定")

base = load_scenario(ROOT / "data" / "sample_market.json")

with st.sidebar:
    st.header("市场设置")
    demand_mw = st.number_input("市场负荷 / MW", min_value=0.0, value=base.demand_mw, step=10.0)
    interval_hours = st.number_input(
        "结算时段 / h", min_value=0.25, value=base.interval_hours, step=0.25
    )
    target_unit_id = st.selectbox(
        "要优化的机组", [offer.unit_id for offer in base.offers], index=0
    )
    engine_name = st.selectbox("出清引擎", ["内置统一出清价", "PyPSA"])
    decision_mode = st.selectbox("决策模式", ["单场景利润最大化", "不确定性 / 风险分析"])

    st.divider()
    st.header("候选报价")
    bid_start = st.number_input("最低报价", min_value=0.0, value=180.0, step=10.0)
    bid_stop = st.number_input("最高报价", min_value=0.0, value=400.0, step=10.0)
    bid_step = st.number_input("报价步长", min_value=0.1, value=10.0, step=1.0)

    if decision_mode == "不确定性 / 风险分析":
        st.divider()
        st.header("压力测试")
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

st.subheader("机组与报价数据")
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

edited_df = st.data_editor(
    source_df,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    column_config={
        "unit_id": st.column_config.TextColumn("机组"),
        "quantity_mw": st.column_config.NumberColumn("申报容量 MW", min_value=0.0),
        "bid_price": st.column_config.NumberColumn("当前报价", min_value=0.0),
        "marginal_cost": st.column_config.NumberColumn("真实边际成本", min_value=0.0),
    },
)

source_label = {
    "synthetic": "仿真构造数据",
    "course": "课程材料",
    "platform": "老师仿真平台",
    "public": "公开市场数据",
    "unknown": "来源未标记",
}.get(base.data_source, base.data_source)
st.caption(f"当前场景数据来源：{source_label}。后续接老师网页时会保留来源标记。")

st.info(
    "目标机组的候选报价会逐个送入出清引擎。单场景模式寻找当前输入下利润最高的报价；"
    "风险模式还会同时测试负荷和竞争者报价变化，避免只对一种情况过拟合。"
)

run = st.button("开始搜索推荐报价", type="primary", use_container_width=True)

if run:
    try:
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
        st.error(str(exc))
    else:
        if decision_mode == "单场景利润最大化":
            best = result.best
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("推荐报价", f"{best.bid_price:.2f}")
            c2.metric(
                "出清价格",
                "-" if best.clearing_price is None else f"{best.clearing_price:.2f}",
            )
            c3.metric("预计中标", f"{best.accepted_mw:.2f} MW")
            c4.metric("预计利润", f"{best.profit:,.2f}")

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

            left, right = st.columns(2)
            with left:
                st.subheader("报价—利润曲线")
                st.line_chart(trials_df.set_index("报价")[["利润"]])
            with right:
                st.subheader("报价—中标电量")
                st.line_chart(trials_df.set_index("报价")[["中标电量MW"]])

            st.subheader("全部试算结果")
            st.dataframe(trials_df, use_container_width=True, hide_index=True)
            st.download_button(
                "导出试算结果 CSV",
                trials_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="powerbid_single_scenario.csv",
                mime="text/csv",
            )
        else:
            best = result.best
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("推荐报价", f"{best.bid_price:.2f}")
            c2.metric("期望利润", f"{best.expected_profit:,.2f}")
            c3.metric("下行情景利润", f"{best.downside_profit:,.2f}")
            c4.metric("最差情景利润", f"{best.worst_profit:,.2f}")

            st.caption(
                f"风险得分 {best.score:,.2f} · 预计中标 {best.expected_accepted_mw:.2f} MW · "
                f"可行概率 {best.feasible_probability:.0%}"
            )

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
            left, right = st.columns(2)
            with left:
                st.subheader("报价—收益 / 风险")
                st.line_chart(
                    risk_df.set_index("报价")[["期望利润", "下行情景利润", "最差情景利润"]]
                )
            with right:
                st.subheader("报价—风险得分")
                st.line_chart(risk_df.set_index("报价")[["风险得分"]])

            st.subheader("推荐报价在各压力情景下的表现")
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
            st.dataframe(outcome_df, use_container_width=True, hide_index=True)

            with st.expander("查看全部候选报价"):
                st.dataframe(risk_df, use_container_width=True, hide_index=True)
            st.download_button(
                "导出风险分析 CSV",
                risk_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="powerbid_risk_analysis.csv",
                mime="text/csv",
            )
