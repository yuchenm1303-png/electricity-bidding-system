"""Offline 24h thermal commitment and physical screening for bidding research."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from powerbid.physical_strategy_audit import (  # noqa: E402
    best_physical_candidate,
    screen_strategy_results,
)
from powerbid.pmss_integration import snapshot_from_pmss  # noqa: E402
from powerbid.strategy_lab import compare_strategies, stress_grid  # noqa: E402
from powerbid.unit_commitment import (  # noqa: E402
    CommitmentSolveError,
    ThermalConstraints,
    optimize_unit_commitment,
)

st.set_page_config(page_title="PowerBid · 机组约束优化", layout="wide")
st.title("机组约束优化 · 24小时运行计划")
st.caption("独立价格预测 → 机组启停与爬坡 MILP → 运行计划 → 报价策略物理筛查")
st.warning(
    "离线研究模式：本页面不向老师 PMSS 保存报价或执行出清。"
    "24小时机组计划依据外部预测电价，不等同于 PMSS 中标曲线。"
)
upload = st.file_uploader(
    "上传已脱敏的 PMSS 只读 JSON 快照",
    type=["json"],
    key="unit_commitment_snapshot",
)
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
except (KeyError, ValueError, TypeError, UnicodeDecodeError) as exc:
    st.error(f"快照解析失败：{exc}")
    st.stop()

if raw.get("historicalBacktestOnly"):
    st.warning(
        "此快照的负荷可能是历史已出清发电量代理，仅供离线回测；"
        "不可将其伪称为未来负荷预测。"
    )
unit_names = {u.unit_id: u.name for u in snapshot.units}
with st.form("unit_commitment_form"):
    unit_id = st.selectbox(
        "目标机组", list(unit_names), format_func=lambda unit: unit_names[unit]
    )
    unit = snapshot.unit(unit_id)
    st.caption(
        f"PMSS 快照参考：最大可调容量 {unit.capacity_mw:g} MW，"
        f"最小可调出力 {unit.min_power_mw:g} MW，"
        f"runningCost {unit.running_cost:g}（财务口径尚需课程核验）。"
    )
    st.markdown("**必须人工核对的机组参数**")
    a, b = st.columns(2)
    min_mw = a.number_input(
        "最小稳定发电 MW", min_value=0.0, max_value=float(unit.capacity_mw),
        value=float(unit.min_power_mw),
    )
    max_mw = b.number_input(
        "最大允许出力 MW", min_value=0.01, value=float(unit.capacity_mw),
    )
    c, d = st.columns(2)
    ramp_up = c.number_input("运行爬坡上限 MW/小时", min_value=0.0, value=None)
    ramp_down = d.number_input("运行降坡上限 MW/小时", min_value=0.0, value=None)
    e, f = st.columns(2)
    startup_ramp = e.number_input("启动小时最高出力 MW", min_value=0.0, value=None)
    shutdown_ramp = f.number_input("停机前一小时最高出力 MW", min_value=0.0, value=None)
    g, h = st.columns(2)
    min_up = g.number_input("最短连续开机小时", min_value=1, step=1, value=None)
    min_down = h.number_input("最短连续停机小时", min_value=1, step=1, value=None)
    i, j = st.columns(2)
    startup_cost = i.number_input("每次启动成本（与电价利润统一货币单位）", min_value=0.0, value=None)
    shutdown_cost = j.number_input("每次停机成本", min_value=0.0, value=None)
    k, m = st.columns(2)
    initial_online = k.checkbox("上一小时机组处于开机状态", value=False)
    initial_mw = m.number_input("上一小时实际出力 MW", min_value=0.0, value=0.0)
    initial_hours = st.number_input(
        "截至上一小时，当前开/停状态已持续小时数",
        min_value=1, step=1, value=None,
    )

    st.markdown("**必须提供独立的24小时电价预测**")
    price_values = st.text_area(
        "24个小时的预测价格（逗号或换行分隔）",
        value="",
        placeholder="逐小时填写24个预测价格；不可用事后真实电价冒充预测",
        height=130,
    )
    price_source = st.text_input("预测数据来源与时间标签", value="")
    assumed_cost = st.number_input(
        "假定每MWh边际成本（需核实原字段单位）",
        min_value=0.0, value=float(unit.running_cost),
    )
    terminal_mode = st.selectbox(
        "日末连续开停机要求",
        ["complete", "carryover"],
        format_func=lambda x: (
            "日内满足最短开/停机时间（保守）"
            if x == "complete" else "允许要求延续至次日（保留未完成小时数）"
        ),
    )
    acknowledged = st.checkbox(
        "我已核验技术参数、价格预测的时间与单位，理解这不是 PMSS 真实出清",
        value=False,
    )
    submitted = st.form_submit_button("计算24小时可行运行计划", type="primary")

if not submitted:
    st.stop()
required = {
    "运行爬坡": ramp_up,
    "运行降坡": ramp_down,
    "启动出力": startup_ramp,
    "停机出力": shutdown_ramp,
    "最短开机": min_up,
    "最短停机": min_down,
    "启动成本": startup_cost,
    "停机成本": shutdown_cost,
    "初始状态小时": initial_hours,
}
missing = [name for name, value in required.items() if value is None]
if missing or not acknowledged or not price_source.strip():
    st.error(
        "参数不完整："
        + ("、".join(missing) if missing else "请确认参数与填写预测来源")
    )
    st.stop()
try:
    import re

    price_parts = [
        x.strip() for x in re.split(r"[,，;；\s]+", price_values.strip()) if x.strip()
    ]
    forecast_prices = [float(x) for x in price_parts]
    spec = ThermalConstraints(
        unit_id=unit_id,
        min_mw=float(min_mw),
        max_mw=float(max_mw),
        ramp_up_mw=float(ramp_up),
        ramp_down_mw=float(ramp_down),
        startup_ramp_mw=float(startup_ramp),
        shutdown_ramp_mw=float(shutdown_ramp),
        min_up_hours=int(min_up),
        min_down_hours=int(min_down),
        startup_cost=float(startup_cost),
        shutdown_cost=float(shutdown_cost),
        initial_on=initial_online,
        initial_mw=float(initial_mw),
        initial_state_hours=int(initial_hours),
    )
    plan = optimize_unit_commitment(
        spec,
        forecast_prices,
        energy_cost_per_mwh=float(assumed_cost),
        forecast_source=price_source,
        terminal_mode=terminal_mode,
    )
except (RuntimeError, ValueError, CommitmentSolveError) as exc:
    st.error(f"无法得到可行的运行计划：{exc}")
    st.stop()

cols = st.columns(4)
cols[0].metric("计划发电量", f"{plan.total_energy_mwh:,.1f} MWh")
cols[1].metric("预测能源毛利", f"{plan.gross_margin:,.2f}")
cols[2].metric("启停成本", f"{plan.transition_cost:,.2f}")
cols[3].metric("预测净收益", f"{plan.net_margin:,.2f}")
if plan.remaining_required_hours:
    st.info(
        f"日末状态的最短运行/停机要求仍须在次日满足："
        f"{plan.remaining_required_hours} 小时。"
    )

hourly = pd.DataFrame(
    {
        "时段": h.period,
        "运行状态": "开机" if h.online else "停机",
        "计划出力 MW": h.power_mw,
        "外部预测电价": h.forecast_price,
        "小时能源毛利": h.energy_margin,
        "当小时启停成本": h.transition_cost,
        "小时净收益": h.net_margin,
    }
    for h in plan.hourly
)
st.subheader("机组计划出力与收益")
st.line_chart(hourly.set_index("时段")[["计划出力 MW"]])
st.dataframe(hourly, hide_index=True, use_container_width=True)

st.subheader("已有报价策略的物理可执行性筛查")
st.caption(
    "独立使用本地简化出清引擎的候选中标量，不会把当前运行计划直接当作中标计划。"
    "该审计只能发现明显的技术限制冲突，并不能证明网络约束下可执行。"
)
try:
    comparison = compare_strategies(
        snapshot,
        unit_id,
        markups=(0, 25, 50, 100),
        scenarios=stress_grid(demand_deviation=0.03, peer_price_deviation=0.03),
    )
    audit_rows = screen_strategy_results(
        comparison.ranked, spec, terminal_mode=terminal_mode
    )
    screened = best_physical_candidate(audit_rows)
    st.dataframe(
        pd.DataFrame(
            {
                "候选策略": entry.strategy_name,
                "满足物理约束的情景比例": entry.physically_feasible_probability,
                "代理模型收益评分": entry.proxy_score,
                "问题摘要": "；".join(entry.sample_violations[:2]) or "未发现",
            }
            for entry in audit_rows
        ),
        hide_index=True,
        use_container_width=True,
    )
    if screened:
        st.success(f"在当前显式机组约束下，筛选得到候选策略：{screened.strategy_name}")
    else:
        st.warning(
            "在当前机组约束与测试情景下，没有任何候选报价在全部情景中通过物理筛查。"
            "不要直接提交本地模型的高利润策略。"
        )
except ValueError as exc:
    st.warning(f"本次无法完成报价策略物理筛查：{exc}")

export = {
    "notice": "OFFLINE UNIT COMMITMENT PLAN - NOT PMSS BIDDING OR CLEARING",
    "unitId": spec.unit_id,
    "forecastSource": plan.forecast_source,
    "terminalMode": plan.terminal_mode,
    "remainingRequiredHours": plan.remaining_required_hours,
    "hours": [
        {
            "period": h.period,
            "online": h.online,
            "powerMw": h.power_mw,
            "started": h.started,
            "stopped": h.stopped,
            "priceForecast": h.forecast_price,
            "netMargin": h.net_margin,
        }
        for h in plan.hourly
    ],
}
st.download_button(
    "导出24小时机组计划（仅供人工审核）",
    json.dumps(export, indent=2, ensure_ascii=False).encode("utf-8"),
    file_name="powerbid_physical_plan.json",
    mime="application/json",
)
st.caption(
    "计算的预测利润仅以输入电价为外生常数。尚未考虑报价本身影响节点电价、"
    "电网阻塞、备用、机组热态启停、日前实时耦合与PMSS实际结算。"
)
