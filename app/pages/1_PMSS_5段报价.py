"""PMSS read-only snapshot workflow; no platform credentials enter Streamlit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from powerbid.pmss_diagnostics import (  # noqa: E402
    analyze_historical_network,
    compare_baseline_to_pmss,
)
from powerbid.pmss_integration import snapshot_from_pmss  # noqa: E402
from powerbid.pmss_strategy import optimize_segmented_bid  # noqa: E402

st.set_page_config(page_title="PMSS · 五段报价优化", layout="wide")
st.title("PMSS · 24 小时五段报价")
st.caption("只读快照 → 本地出清近似仿真 → 推荐分段报价。没有报价提交和 PMSS 出清按钮。")
st.info(
    "本页使用已抓取的真实 PMSS 机组/报价数据，但候选报价通过 PowerBid 内置"
    "单区域统一价教学引擎评估。结果不是 PMSS 的节点电价、潮流或真实出清。"
)

st.markdown(
    "上传不含账号、Cookie、Token 的 JSON 快照，包含 "
    "\`unitTree\`、\`unitBids\`、\`marketSystem\`、"
    "\`demandForecastMw\`（24 个数）和 \`forecastSource\`。"
)
upload = st.file_uploader("选择 PMSS 只读数据快照", type=["json"])
if upload is None:
    st.stop()

try:
    raw = json.loads(upload.getvalue().decode("utf-8"))
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"],
        unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
    st.error(f"PMSS 快照字段无法解析：{exc}")
    st.stop()

st.success(
    f"已载入 {len(snapshot.units)} 台机组、{snapshot.period_num} 个时段；"
    f"负荷预测来源：{snapshot.forecast_source}"
)
st.dataframe(
    pd.DataFrame([
        {
            "机组": u.name,
            "类型": u.unit_type,
            "额定可调容量 MW": u.capacity_mw,
            "最小可调出力 MW": u.min_power_mw,
            "runningCost": u.running_cost,
        }
        for u in snapshot.units
    ]),
    use_container_width=True,
    hide_index=True,
)
st.caption(
    "注意：runningCost 在当前简化模拟中按每 MWh 边际成本使用；"
    "真实 PMSS 对该字段的财务口径仍需按课程规则核验。"
)

if raw.get("historicalBacktestOnly"):
    if raw.get("loadSourceKind") == "PMSS_DA_SCENE_LOAD_INPUT":
        st.info(
            "该快照采用 PMSS 历史场景的实际日前负荷输入（不是未来预测）。"
            "只能用于该历史案例的分析与模型回测。"
        )
    else:
        st.warning(
            "这份旧快照使用历史已出清总发电量作为负荷代理，"
            "不等于真实负荷预测；只能验证算法流程。"
        )

observed = raw.get("results")
if isinstance(observed, dict) and observed.get("periodNum") == 24:
    st.subheader("PMSS 真实已出清结果（只读）")
    st.caption(
        f"历史案例：{raw.get('caseDate', '未标注日期')} · "
        "下方是真实 PMSS 已出清数据，不是本地报价优化的预测结果。"
    )
    unit_tab, node_tab, branch_tab = st.tabs(
        ["机组中标", "节点电价", "支路潮流"]
    )

    def _values(row, field):
        series = row.get(field, {})
        if isinstance(series, dict):
            return series.get("datas", [])
        return series if isinstance(series, (list, tuple)) else []

    with unit_tab:
        units_data = observed.get("unitResults") or []
        if units_data:
            picked_unit = st.selectbox(
                "查看机组结果",
                range(len(units_data)),
                format_func=lambda i: units_data[i].get("elementName")
                or units_data[i].get("name", str(i)),
                key="pmss_actual_unit",
            )
            item = units_data[picked_unit]
            st.dataframe(
                pd.DataFrame({
                    "时段": range(1, 25),
                    "中标出力 MW": _values(item, "power")
                    or item.get("accepted_mw", []),
                    "实际出清价格": _values(item, "price")
                    or item.get("clearing_prices", []),
                    "平台记录收入": _values(item, "income"),
                }),
                hide_index=True,
                use_container_width=True,
            )
    with node_tab:
        nodes_data = observed.get("nodalPrices") or []
        if nodes_data:
            picked_node = st.selectbox(
                "查看节点",
                range(len(nodes_data)),
                format_func=lambda i: nodes_data[i].get("elementName")
                or nodes_data[i].get("name", str(i)),
                key="pmss_actual_node",
            )
            item = nodes_data[picked_node]
            st.line_chart(
                pd.DataFrame({
                    "时段": range(1, 25),
                    "节点电价": _values(item, "powerFlow") or item.get("lmp", []),
                }).set_index("时段")
            )
    with branch_tab:
        branches_data = observed.get("branchFlows") or []
        if branches_data:
            picked_branch = st.selectbox(
                "查看支路",
                range(len(branches_data)),
                format_func=lambda i: branches_data[i].get("elementName")
                or branches_data[i].get("name", str(i)),
                key="pmss_actual_branch",
            )
            item = branches_data[picked_branch]
            st.dataframe(
                pd.DataFrame({
                    "时段": range(1, 25),
                    "线路潮流 MW": _values(item, "powerFlow")
                    or item.get("flow_mw", []),
                    "首端节点电价": _values(item, "beginNodePrice")
                    or item.get("from_node_price", []),
                    "末端节点电价": _values(item, "endNodePrice")
                    or item.get("to_node_price", []),
                    "影子价格": _values(item, "shadowPrice")
                    or item.get("shadow_price", []),
                    "阻塞盈余": _values(item, "blockSurplus")
                    or item.get("congestion_surplus", []),
                }),
                hide_index=True,
                use_container_width=True,
            )

network_report = None
if isinstance(observed, dict) and observed.get("periodNum") == 24:
    try:
        network_report = analyze_historical_network(observed)
    except (ValueError, TypeError, KeyError) as exc:
        st.warning(f"历史网络诊断不可用：{exc}")

if network_report is not None:
    st.subheader("历史网络阻塞与节点价格")
    st.caption(
        "下面是 PMSS 已发生出清的网络状态，并不是候选报价对节点电价或线路的影响预测。"
    )
    network_hours = pd.DataFrame([
        {
            "时段": hour.hour,
            "节点价格极差": hour.lmp_spread,
            "非零影子价格线路数": hour.nonzero_shadow_branches,
            "最大线路潮流绝对值 MW": hour.max_abs_flow_mw,
            "最大影子价格绝对值": hour.max_abs_shadow,
        }
        for hour in network_report.hourly
    ])
    first, second, third = st.columns(3)
    first.metric("已读取节点", str(network_report.node_count))
    second.metric("已读取线路", str(network_report.branch_count))
    third.metric(
        "出现非零影子价格的时段",
        f"{sum(hour.nonzero_shadow_branches > 0 for hour in network_report.hourly)}/24",
    )
    st.line_chart(network_hours.set_index("时段")[["节点价格极差"]])
    st.dataframe(network_hours, hide_index=True, use_container_width=True)
    st.caption(
        "影子价格非零只代表对应约束在历史解中的边际价值，"
        "不能据此推断线路过载或报价调整后的潮流。"
    )
    st.dataframe(
        pd.DataFrame([
            {
                "线路": b.name or b.element_id,
                "非零影子价格时段": b.hours_nonzero_shadow,
                "影子价格绝对值峰值": b.peak_abs_shadow,
                "历史潮流绝对值峰值 MW": b.peak_abs_flow_mw,
            }
            for b in network_report.most_shadowed[:10]
        ]),
        hide_index=True,
        use_container_width=True,
    )

with st.form("optimize_pmss_curve"):
    unit_names = {u.unit_id: u.name for u in snapshot.units}
    chosen = st.selectbox(
        "目标机组", options=list(unit_names), format_func=lambda k: unit_names[k]
    )
    a, b, c = st.columns(3)
    lower = a.number_input("候选最低报价", value=0.0, min_value=0.0)
    upper = b.number_input("候选最高报价", value=1000.0, min_value=0.0)
    step = c.number_input("报价搜索步长", value=100.0, min_value=0.01)
    e, f = st.columns(2)
    intervals = e.slider("局部搜索迭代轮数", 1, 15, value=6)
    granularity = f.number_input("分段电量边界调整步长 MW（0 表示自动）", value=0.0, min_value=0.0)
    start = st.form_submit_button("本地模拟并生成五段曲线", type="primary")

if not start:
    st.stop()
if lower > upper or (upper - lower) / step > 200:
    st.error("请检查报价范围；最多支持 201 个候选价格。")
    st.stop()

prices = [round(lower + step * i, 9) for i in range(int((upper - lower) / step) + 1)]
if abs(prices[-1] - upper) > 1e-7:
    prices.append(float(upper))

try:
    with st.spinner("正在进行本地模拟"):
        result = optimize_segmented_bid(
            snapshot,
            chosen,
            candidate_prices=prices,
            quantity_step_mw=granularity or None,
            iterations=intervals,
        )
except ValueError as exc:
    st.error(str(exc))
    st.stop()

base, best = result.baseline, result.recommended
col1, col2, col3 = st.columns(3)
col1.metric("原始曲线模拟利润", f"{base.total_profit:,.2f}")
col2.metric("推荐曲线模拟利润", f"{best.total_profit:,.2f}")
col3.metric("本地试算次数", result.evaluated_curves)

if isinstance(observed, dict) and observed.get("periodNum") == 24:
    try:
        backtest = compare_baseline_to_pmss(
            target_unit_id=chosen, baseline=base, results=observed,
        )
    except (ValueError, TypeError, KeyError) as exc:
        st.warning(f"模型历史误差未能计算：{exc}")
    else:
        st.subheader("基准策略：PowerBid 模拟与 PMSS 真实中标的偏差")
        st.caption(
            "这里仅比较原始报价曲线的历史模拟误差；推荐的新报价尚未在 PMSS"
            " 出清，不能据此判断真实收益一定提升。"
        )
        left, middle, right = st.columns(3)
        left.metric(
            "原始报价出力 MAE",
            f"{backtest.power_mae_mw:,.2f} MW"
            if backtest.power_mae_mw is not None else "无数据",
        )
        middle.metric(
            "出力 RMSE",
            f"{backtest.power_rmse_mw:,.2f} MW"
            if backtest.power_rmse_mw is not None else "无数据",
        )
        right.metric("实际出力覆盖", f"{backtest.observed_power_points}/24")
        st.line_chart(
            pd.DataFrame([
                {
                    "时段": item.hour,
                    "PMSS 实际中标 MW": item.observed_accepted_mw,
                    "PowerBid 原始曲线模拟 MW": item.surrogate_accepted_mw,
                }
                for item in backtest.hours
            ]).set_index("时段")
        )
        st.caption(
            "PMSS 机组价格可能是节点结算价格；PowerBid 仅有单区域统一价格，"
            "两种价格不直接等价。因此这里优先使用中标量误差验证模型。"
        )

st.subheader("推荐价格—电量段")
st.dataframe(
    pd.DataFrame([
        {
            "段号": i,
            "起始 MW": s.start_power,
            "结束 MW": s.end_power,
            "本段 MW": s.quantity_mw,
            "报价": s.price,
        }
        for i, s in enumerate(best.segments, 1)
    ]),
    hide_index=True,
    use_container_width=True,
)
st.subheader("24 小时模拟")
hourly = pd.DataFrame([
    {
        "时段": h.period,
        "市场负荷预测 MW": h.demand_mw,
        "单区域出清价": h.clearing_price,
        "目标机组中标 MW": h.target_accepted_mw,
        "预计利润": h.target_profit,
    }
    for h in best.hours
])
st.line_chart(hourly.set_index("时段")[["预计利润"]])
st.dataframe(hourly, hide_index=True, use_container_width=True)

review = {
    "source": "PowerBid surrogate dry-run; not PMSS clearing",
    "unitId": chosen,
    "marketTypeAtom": snapshot.limits.market_type,
    "startPeriod": 1,
    "endPeriod": snapshot.period_num,
    "segmentDatas": [
        {
            "startPower": s.start_power,
            "endPower": s.end_power,
            "price": s.price,
            "segmentOrder": i,
        }
        for i, s in enumerate(best.segments, 1)
    ],
}
st.download_button(
    "下载分段报价审核文件（不会提交平台）",
    json.dumps(review, ensure_ascii=False, indent=2).encode("utf-8"),
    file_name="powerbid_pmss_curve_review.json",
    mime="application/json",
)
st.warning(
    "此结果仅用于本地模拟与人工审阅。缺少实际线路约束、节点 LMP、"
    "机组启停/爬坡、最小出力等约束；不得视为 PMSS 已验证的最优报价。"
)
