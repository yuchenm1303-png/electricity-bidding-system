"""Independent offline 24h DC network + unit commitment bidding research page."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, fields
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from powerbid.joint_feedback import compare_joint_baseline_history  # noqa: E402
from powerbid.joint_market import JointInfeasibleError  # noqa: E402
from powerbid.joint_strategy import compare_joint_bids  # noqa: E402
from powerbid.network_dispatch import network_from_dict  # noqa: E402
from powerbid.pmss_integration import snapshot_from_pmss  # noqa: E402
from powerbid.strategy_lab import BidPolicy, DemandStress  # noqa: E402
from powerbid.unit_commitment import ThermalConstraints  # noqa: E402

st.set_page_config(page_title="PowerBid · 联合优化研究", layout="wide")
st.title("24小时网络与机组联合报价优化")
st.caption("同一个混合整数模型：机组启停 + 最小出力 + 爬坡 + 节点负荷 + 线路潮流")
st.warning(
    "这是独立、无损的 DC + 机组组合离线研究模型，不是老师 PMSS 的真实出清。"
    "程序不会调用 PMSS 保存报价或运行市场出清接口。"
)
st.info(
    "与旧模型的区别：以前先做节点出清，再检查机组运行约束；"
    "现在在同一模型里联合求解24小时出力、开停机和线路输送。"
    "解出整数开停机状态后，再固定状态求解连续 LP 生成示意节点价格。"
)

with st.expander("立即体验：项目自带的合成两节点演示数据"):
    st.markdown(
        "可在仓库中找到以下三个文件。它们全部是 synthetic 教学数据，"
        "**不是真实 PMSS 电网拓扑或老师平台出清结果**。"
    )
    st.code(
        "data/examples/synthetic_dc_pmss.json\n"
        "data/examples/synthetic_dc_network.json\n"
        "data/examples/synthetic_joint_technical.json",
        language="text",
    )
    st.caption(
        "上传时务必使用已经脱敏的数据，不包含账号、Cookie、Token、"
        "内部服务器地址或完整原始登录会话。"
    )

col_a, col_b, col_c = st.columns(3)
with col_a:
    pmss_file = st.file_uploader(
        "PMSS 脱敏快照（机组报价与24小时场景负荷）",
        type=["json"], key="joint_pmss",
    )
with col_b:
    grid_file = st.file_uploader(
        "核验过的节点—线路网络文件",
        type=["json"], key="joint_network",
    )
with col_c:
    physical_file = st.file_uploader(
        "全部机组的运行约束（每台都必须提供）",
        type=["json"], key="joint_physical",
    )
if pmss_file is None or grid_file is None or physical_file is None:
    st.stop()

try:
    raw = json.loads(pmss_file.getvalue().decode("utf-8"))
    grid = json.loads(grid_file.getvalue().decode("utf-8"))
    physical_raw = json.loads(physical_file.getvalue().decode("utf-8"))
    if not isinstance(physical_raw, dict):
        raise ValueError("技术参数必须是机组ID映射JSON对象")
    needed = {f.name for f in fields(ThermalConstraints)}
    if any(
        not isinstance(item, dict) or set(item) != needed
        for item in physical_raw.values()
    ):
        raise ValueError("每台机组技术参数必须且只能包含 ThermalConstraints 全部字段")
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"],
        unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    network = network_from_dict(grid)
    physical = {
        str(unit_id): ThermalConstraints(**payload)
        for unit_id, payload in physical_raw.items()
    }
    if set(physical) != {item.unit_id for item in snapshot.units}:
        raise ValueError("必须完整提供所有机组的约束，机组ID与快照严格对应")
except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
    st.error(f"读取数据失败：{exc}")
    st.stop()

if raw.get("syntheticExample"):
    st.warning("当前为 PowerBid 自带合成教学案例，不是老师 PMSS 真实电网。")
if raw.get("historicalBacktestOnly"):
    st.warning(
        "此快照是历史场景，仅能做事后检验。历史数据不能被称为未来需求或未来电价预测。"
    )
st.caption(
    f"加载成功：机组 {len(snapshot.units)} 台、"
    f"网络节点 {len(network.buses)} 个、"
    f"线路 {len(network.lines)} 条，"
    f"24小时时段。数据来源：{network.topology_source}"
)

with st.form("joint_dispatch_options"):
    target = st.selectbox(
        "目标发电机组",
        tuple(x.unit_id for x in snapshot.units),
        format_func=lambda x: f"{snapshot.unit(x).name} · {x}",
    )
    c1, c2, c3 = st.columns(3)
    risk = c1.slider("风险厌恶系数", 0.0, 1.0, 0.35, 0.05)
    tail = c2.slider("下行概率占比", 0.05, 1.0, 0.25, 0.05)
    stress_type = c3.selectbox(
        "合成市场情景数", ("1 · 中性情景", "3 · 轻度敏感性分析")
    )
    terminal = st.selectbox(
        "日末开停机约束", ("complete", "carryover"),
        format_func=lambda value: (
            "日内完成最短开停机时间"
            if value == "complete" else "允许状态义务延续至次日"
        ),
    )
    confirmed = st.checkbox(
        "我已核实所有机组技术参数、节点拓扑、电抗、线路限额及成本单位；"
        "理解这不是 PMSS 实际出清结果",
        value=False,
    )
    run = st.form_submit_button("运行联合报价策略优化", type="primary")

if not run:
    st.stop()
if not confirmed:
    st.error("请先确认数据来源和技术参数，再运行联合模型。")
    st.stop()

scenarios = (DemandStress("neutral", 1.0, 1.0),)
if stress_type.startswith("3"):
    scenarios = (
        DemandStress("low demand / expensive peers", 0.98, 1.02),
        DemandStress("neutral", 1.0, 1.0),
        DemandStress("high demand / cheap peers", 1.02, 0.98),
    )

policies = (
    BidPolicy("边际成本"),
    BidPolicy("固定加价20", markup=20),
    BidPolicy("分段梯度", markup=5, slope=15),
    BidPolicy("紧张时段溢价", markup=10, slope=10, scarcity_sensitivity=100),
)
try:
    with st.spinner("正在运行24小时混合整数市场求解和固定状态节点电价计算"):
        comparison = compare_joint_bids(
            snapshot,
            network,
            physical,
            target,
            policies=policies,
            scenarios=scenarios,
            risk_aversion=risk,
            tail_fraction=tail,
            terminal_mode=terminal,
        )
except (ValueError, RuntimeError, JointInfeasibleError) as exc:
    st.error(
        f"联合求解未完成：{exc}。如某个情景不可行，不会虚构该情景利润或输出伪可行报价。"
    )
    st.stop()

winner = comparison.recommended
st.subheader("联合约束下的报价策略排名")
summary = st.columns(4)
summary[0].metric("候选中排名第一", winner.name)
summary[1].metric("模拟预期净收益", f"{winner.expected_net_profit:,.2f}")
summary[2].metric("下行模拟净收益", f"{winner.downside_net_profit:,.2f}")
summary[3].metric("实际比较的方案", str(comparison.evaluated))
st.caption(
    "目标机组净收益是基于模型模拟节点价格、中标量与假定边际成本计算，"
    "并扣除该机组的启停成本。未包含 PMSS 真实结算、补偿、备用或其他成本。"
)
st.dataframe(
    pd.DataFrame([
        {
            "策略": x.name,
            "模拟预期净收益": x.expected_net_profit,
            "下行净收益": x.downside_net_profit,
            "最差情景净收益": x.worst_net_profit,
            "期望中标 MWh": x.expected_accepted_mwh,
            "风险评分": x.risk_score,
        }
        for x in comparison.ranked
    ]),
    use_container_width=True, hide_index=True,
)

neutral = next(
    x for x in winner.scenarios if x.name == "neutral"
)
st.subheader("24小时联合出清轨迹（中性情景）")
target_bus = network.unit_bus[target]
df = pd.DataFrame([
    {
        "时段": row.period,
        "目标机组中标 MW": row.accepted_by_unit[target],
        "机组开机": "是" if row.unit_online[target] else "否",
        "机组启动": "是" if row.unit_started[target] else "否",
        "机组停机": "是" if row.unit_stopped[target] else "否",
        "本节点示意 LMP": row.nodal_prices[target_bus],
        "全市场启停成本": row.transition_cost,
    }
    for row in neutral.market.hours
])
st.line_chart(df.set_index("时段")[["目标机组中标 MW"]])
st.dataframe(df, use_container_width=True, hide_index=True)

if network.lines:
    chosen_line = st.selectbox(
        "查看线路潮流", [line.line_id for line in network.lines]
    )
    st.line_chart(
        pd.DataFrame([
            {"时段": x.period, "线路潮流 MW": x.line_flows_mw[chosen_line]}
            for x in neutral.market.hours
        ]).set_index("时段")
    )
st.info(
    "这里的节点电价不是从 MILP 直接读取的影子价格，"
    "而是固定最优开停机状态后重新求解连续 DC-LP 的对偶价格。"
    "属于模型参考价格，不代表老师 PMSS 的实际结算 LMP。"
)

if isinstance(raw.get("results"), dict):
    st.subheader("历史 PMSS 出清结果对照（仅原始申报基线）")
    try:
        backtest = compare_joint_baseline_history(
            snapshot, network, comparison.baseline, target, raw["results"]
        )
    except (ValueError, KeyError, TypeError) as exc:
        st.info(f"历史资料尚不能严格匹配到相同机组、节点、线路与时段：{exc}")
    else:
        m = st.columns(3)
        m[0].metric(
            "目标机组中标 MAE",
            "—" if backtest.target_dispatch_mae_mw is None
            else f"{backtest.target_dispatch_mae_mw:,.3f} MW",
        )
        m[1].metric(
            "全网节点电价 MAE",
            "—" if backtest.all_bus_lmp_mae is None
            else f"{backtest.all_bus_lmp_mae:,.3f}",
        )
        m[2].metric(
            "线路潮流绝对值 MAE",
            "—" if backtest.line_flow_magnitude_mae_mw is None
            else f"{backtest.line_flow_magnitude_mae_mw:,.3f} MW",
        )
        st.caption(
            f"历史覆盖：机组 {backtest.unit_points} 点、"
            f"节点 {backtest.node_points} 点、"
            f"线路 {backtest.line_points} 点。"
            "这是原始报价的模型误差，不是新报价的 PMSS 实测收益。"
        )

export = {
    "notice": "OFFLINE DC+UC JOINT STRATEGY REVIEW ONLY; NOT PMSS CLEARING",
    "targetUnitId": target,
    "strategy": winner.name,
    "networkSource": network.topology_source,
    "demandSource": network.demand_source,
    "pricing": neutral.market.pricing_method,
    "periods": [
        {
            "startPeriod": period.start_period,
            "endPeriod": period.end_period,
            "segmentDatas": [
                {
                    "segmentOrder": number,
                    "startPower": seg.start_power,
                    "endPower": seg.end_power,
                    "price": seg.price,
                }
                for number, seg in enumerate(period.segments, 1)
            ],
        }
        for period in winner.periods
    ],
}
st.download_button(
    "下载联合优化审核文件（不会提交 PMSS）",
    json.dumps(export, ensure_ascii=False, indent=2).encode("utf-8"),
    file_name="powerbid_joint_strategy_review.json",
    mime="application/json",
)
