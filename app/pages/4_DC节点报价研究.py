"""Offline DC network bidding research: no PMSS credentials or write endpoints."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from powerbid.network_dispatch import network_from_dict  # noqa: E402
from powerbid.network_feedback import compare_dc_baseline_to_pmss  # noqa: E402
from powerbid.network_strategy import compare_network_policies  # noqa: E402
from powerbid.pmss_integration import snapshot_from_pmss  # noqa: E402
from powerbid.strategy_lab import DemandStress, stress_grid  # noqa: E402
from powerbid.unit_commitment import ThermalConstraints  # noqa: E402

st.set_page_config(page_title="PowerBid · 网络约束策略研究", layout="wide")
st.title("网络约束策略研究 · 节点电价与阻塞")
st.warning(
    "这是独立的简化 DC 网络出清模型，不是老师 PMSS 的真实出清。"
    "页面不会向老师平台提交报价、修改数据或运行出清。"
)
st.caption(
    "需要核实的节点/线路 ID、机组接入节点、线路电抗（标幺值）、"
    "线路 MW 限额、baseMva 与逐节点24小时负荷。没有这些数据时不会猜测网络。"
)

u, v = st.columns(2)
with u:
    pmss_upload = st.file_uploader(
        "第一步：上传脱敏 PMSS 快照（机组、报价、总负荷、可选历史结果）",
        type=["json"],
        key="network_pmss_input",
    )
with v:
    network_upload = st.file_uploader(
        "第二步：上传已核验的 DC 网络 JSON（节点、线路、电抗、逐节点负荷）",
        type=["json"],
        key="network_verified_input",
    )

with st.expander("查看网络 JSON 格式说明"):
    st.code(
        '''{
  "buses": ["BUS-A", "BUS-B"],
  "lines": [
    {"lineId": "LINE-1", "fromBus": "BUS-A", "toBus": "BUS-B",
     "reactancePu": 0.1, "limitMw": 80.0}
  ],
  "unitBus": {"GEN-1": "BUS-A", "GEN-2": "BUS-B"},
  "hourlyDemandMw": {
    "BUS-A": [0, 0, "… 共24个数值"],
    "BUS-B": [200, 200, "… 共24个数值"]
  },
  "slackBus": "BUS-A",
  "baseMva": 100.0,
  "topologySource": "核实数据出处",
  "demandSource": "与 PMSS 快照 forecastSource 完全一致"
}''',
        language="json",
    )
    st.caption(
        "上面是字段示意，不是能直接提交的有效网络数据。"
        "负荷每个节点都必须有24个数，真实机组和节点 ID 必须一一对应。"
    )

physical_upload = st.file_uploader(
    "可选：上传独立核实的机组物理参数 JSON，以便筛除不符合启停与爬坡要求的报价",
    type=["json"],
    key="network_physical_input",
)
with st.expander("查看可选物理约束文件字段"):
    st.code(
        "必须使用 ThermalConstraints 的确切字段："
        "unit_id、min_mw、max_mw、ramp_up_mw、ramp_down_mw、"
        "startup_ramp_mw、shutdown_ramp_mw、min_up_hours、min_down_hours、"
        "startup_cost、shutdown_cost、initial_on、initial_mw、initial_state_hours。"
        "这些字段均应取自核实的机组资料；不可猜测或默认置零。",
        language="text",
    )

if pmss_upload is None or network_upload is None:
    st.stop()

try:
    pmss = json.loads(pmss_upload.getvalue().decode("utf-8"))
    net = json.loads(network_upload.getvalue().decode("utf-8"))
    snapshot = snapshot_from_pmss(
        unit_tree=pmss["unitTree"],
        unit_bids=pmss["unitBids"],
        market_system=pmss["marketSystem"],
        demand_forecast_mw=pmss["demandForecastMw"],
        forecast_source=pmss["forecastSource"],
    )
    network = network_from_dict(net)
    physical = None
    if physical_upload is not None:
        from dataclasses import fields

        physical_raw = json.loads(physical_upload.getvalue().decode("utf-8"))
        if not isinstance(physical_raw, dict) or set(physical_raw) != {
            field.name for field in fields(ThermalConstraints)
        }:
            raise ValueError("Physical JSON fields must exactly match ThermalConstraints")
        physical = ThermalConstraints(**physical_raw)
except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
    st.error(f"数据不完整或无法识别：{exc}")
    st.stop()

if pmss.get("historicalBacktestOnly"):
    st.warning(
        "PMSS 快照是历史案例，仅可用于事后回测。"
        "不能把该日的已出清数据或观测 LMP 当成未来预测。"
    )

st.caption(
    f"已载入 {len(network.buses)} 节点、{len(network.lines)} 线路、"
    f"{len(snapshot.units)} 机组。"
    f"电网来源：{network.topology_source}；负荷来源：{network.demand_source}"
)
with st.form("dc_bidding_study"):
    ids = [u.unit_id for u in snapshot.units]
    target_id = st.selectbox(
        "目标机组", ids,
        format_func=lambda id_: f"{snapshot.unit(id_).name} · {id_}",
    )
    a, b, c = st.columns(3)
    risk = a.slider("风险厌恶系数", 0.0, 1.0, 0.35, 0.05)
    load_uncertainty = b.slider("节点负荷情景波动", 0.0, 0.15, 0.03, 0.01)
    peer_uncertainty = c.slider("竞争报价情景波动", 0.0, 0.15, 0.03, 0.01)
    run = st.form_submit_button("运行24小时网络约束策略比较", type="primary")

if not run:
    st.stop()

try:
    from powerbid.network_strategy import verify_network_inputs

    verify_network_inputs(snapshot, network, target_id)
    with st.spinner("正在使用本地 DC 线性优化器计算24小时节点电价"):
        scenarios = stress_grid(
            demand_deviation=load_uncertainty,
            peer_price_deviation=peer_uncertainty,
        )
        comparison = compare_network_policies(
            snapshot,
            network,
            target_id,
            scenarios=scenarios,
            risk_aversion=risk,
            physical=physical,
        )
except (RuntimeError, ValueError) as exc:
    st.error(f"网络策略比较未完成：{exc}")
    st.stop()

st.subheader("网络约束下的模拟策略排名")
best = comparison.recommended
q = st.columns(4)
q[0].metric("最优测试策略", best.name)
q[1].metric("模拟预期毛利", f"{best.expected_margin:,.2f}")
q[2].metric("尾部下行毛利", f"{best.downside_margin:,.2f}")
q[3].metric("实际比较候选数", str(comparison.evaluated))
st.caption(
    "注意：模拟毛利 = DC节点电价 × 模拟中标电量 - 常量运行成本。"
    "未在网络出清时联合求解启停与爬坡；如果提供物理参数，仅在出清后进行排除筛查。"
    "未考虑交流潮流、备用和PMSS实际结算。"
)
st.dataframe(
    pd.DataFrame(
        {
            "报价策略": row.name,
            "物理筛查": "未提供约束" if row.physically_feasible is None
            else ("通过" if row.physically_feasible else "未通过"),
            "期望模拟毛利": row.expected_margin,
            "下行毛利": row.downside_margin,
            "最差情景毛利": row.worst_margin,
            "期望中标 MWh": row.expected_accepted_mwh,
            "评分": row.score,
        }
        for row in comparison.ranked
    ),
    hide_index=True, use_container_width=True,
)

if physical is None:
    st.info(
        "目前没有提供机组运行约束：排名只基于 DC 网络模拟利润，"
        "不能推断策略在实际机组开停机和爬坡约束下可执行。"
    )
else:
    st.success(
        "已提供目标机组物理参数，本次推荐经过所有测试情景的事后物理筛查。"
        "此筛查不能代替网络与多时段约束联合优化。"
    )

st.subheader("中性市场情景 · 节点电价 / 线路潮流")
neutral = next(
    (s for s in best.scenarios if s.name.startswith("demand x1.00 / peer bid x1.00")),
    best.scenarios[0],
)
st.caption(
    f"展示场景：{neutral.name}；网络和节点负荷属于上传的输入，"
    "电价和潮流是模型重算结果，不是 PMSS 历史真实观测。"
)
rows = [
    {
        "小时": h.period,
        "机组中标 MW": h.dispatched_mw,
        "本节点 DC 电价": h.target_lmp,
        "目标机组小时毛利": h.margin,
    }
    for h in neutral.hours
]
hours_df = pd.DataFrame(rows)
st.line_chart(hours_df.set_index("小时")[["本节点 DC 电价"]])
st.dataframe(hours_df, hide_index=True, use_container_width=True)

selected_line = st.selectbox(
    "选择要查看的线路模拟潮流",
    [line.line_id for line in network.lines],
    index=0,
) if network.lines else None
if selected_line:
    flow_df = pd.DataFrame(
        {
            "小时": h.period,
            "模拟潮流 MW": h.branch_flows_mw[selected_line],
        }
        for h in neutral.hours
    )
    st.line_chart(flow_df.set_index("小时"))

if isinstance(pmss.get("results"), dict):
    st.subheader("真实 PMSS 历史案例对照（仅原始报价，禁止跨方案冒认）")
    try:
        from powerbid.network_strategy import evaluate_network_plan

        original = evaluate_network_plan(
            snapshot, network, target_id,
            "PMSS 原始已申报曲线（DC模型重算）",
            snapshot.bids[target_id],
            (DemandStress("normal"),),
        )
        history = compare_dc_baseline_to_pmss(
            snapshot, network, original, target_id, pmss["results"]
        )
    except (ValueError, RuntimeError) as exc:
        st.info(f"本次历史样本无法严格匹配拓扑/机组/线路ID：{exc}")
    else:
        hist_cols = st.columns(4)
        hist_cols[0].metric(
            "历史中标出力 MAE", 
            "—" if history.target_dispatch_mae_mw is None
            else f"{history.target_dispatch_mae_mw:.3f} MW",
        )
        hist_cols[1].metric(
            "目标机组价格 MAE",
            "—" if history.target_price_mae is None
            else f"{history.target_price_mae:.3f}",
        )
        hist_cols[2].metric(
            "全网节点电价 MAE",
            "—" if history.nodal_price_mae is None
            else f"{history.nodal_price_mae:.3f}",
        )
        hist_cols[3].metric(
            "线路绝对潮流 MAE",
            "—" if history.line_absolute_flow_mae_mw is None
            else f"{history.line_absolute_flow_mae_mw:.3f} MW",
        )
        st.caption(
            "此处仅用上传的原始申报曲线对比同日已出清历史结果，"
            "不代表新报价在 PMSS 出清后的结果。"
            f"有效覆盖：节点 {history.observed_network_node_points}、"
            f"线路 {history.observed_line_flow_points} 个时段点。"
        )

review = {
    "notice": "OFFLINE NETWORK DC SURROGATE - NOT PMSS VERIFIED OR SUBMITTED",
    "unitId": target_id,
    "networkSource": network.topology_source,
    "demandSource": network.demand_source,
    "strategy": best.name,
    "riskScore": best.score,
    "periods": [
        {
            "startPeriod": p.start_period,
            "endPeriod": p.end_period,
            "segmentDatas": [
                {
                    "segmentOrder": i,
                    "startPower": seg.start_power,
                    "endPower": seg.end_power,
                    "price": seg.price,
                }
                for i, seg in enumerate(p.segments, 1)
            ],
        }
        for p in best.periods
    ],
}
st.download_button(
    "下载本地网络模型策略审核 JSON（不提交）",
    json.dumps(review, ensure_ascii=False, indent=2).encode("utf-8"),
    file_name="powerbid_dc_strategy_review.json",
    mime="application/json",
)
