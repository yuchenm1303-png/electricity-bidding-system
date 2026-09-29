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
from powerbid.scenario_io import load_scenario  # noqa: E402

st.set_page_config(page_title="PowerBid Lab", page_icon="⚡", layout="wide")

st.title("PowerBid Lab")
st.caption("发电商报价决策教学原型 · 当前示例数据为仿真数据，不代表真实市场")

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

    st.divider()
    st.header("候选报价")
    bid_start = st.number_input("最低报价", min_value=0.0, value=180.0, step=10.0)
    bid_stop = st.number_input("最高报价", min_value=0.0, value=400.0, step=10.0)
    bid_step = st.number_input("报价步长", min_value=0.1, value=10.0, step=1.0)

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

st.info(
    "这里可以直接改负荷、竞争机组报价、容量和成本。系统会把目标机组的候选报价逐个送入出清引擎，再比较利润。"
)

run = st.button("开始搜索最优报价", type="primary", use_container_width=True)

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
        )
        engine = (
            PyPSAClearingEngine()
            if engine_name == "PyPSA"
            else UniformPriceClearingEngine()
        )
        optimizer = GridSearchBidOptimizer(engine)
        result = optimizer.optimize(
            scenario,
            price_grid(float(bid_start), float(bid_stop), float(bid_step)),
        )
    except Exception as exc:  # UI boundary: show actionable error instead of crashing
        st.error(str(exc))
    else:
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
                    "报价": t.bid_price,
                    "出清价格": t.clearing_price,
                    "中标电量MW": t.accepted_mw,
                    "收入": t.revenue,
                    "变动成本": t.variable_cost,
                    "利润": t.profit,
                    "可行": t.feasible,
                }
                for t in result.trials
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
