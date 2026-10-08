"""Advanced *offline* PMSS strategy lab. No credentials or PMSS write endpoints."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from powerbid.pmss_integration import snapshot_from_pmss  # noqa: E402
from powerbid.strategy_lab import compare_strategies, stress_grid  # noqa: E402

st.set_page_config(page_title="PowerBid · 策略研究室", layout="wide")
st.title("策略研究室 · 24 小时报价与风险比较")
st.caption("本地策略生成 → 24小时多段报价 → 单区域近似出清 → 多情景收益/风险排序")
st.warning(
    "研究模式：不会写入老师 PMSS、不会触发真实出清。以下所有利润、电价与"
    "中标量均来自简化教学引擎，绝非 PMSS 出清结果或真实市场预测。"
)

upload = st.file_uploader(
    "上传已脱敏 PMSS 只读快照（与五段报价页面使用相同格式）",
    type=["json"],
    key="strategy_lab_upload",
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
    st.error(f"无法解析 PMSS 快照：{exc}")
    st.stop()

if raw.get("historicalBacktestOnly"):
    st.warning(
        "注意：该快照标记为历史回测，负荷可能来自事后发电量代理值，"
        "不得用于未来价格预测或正式报价建议。"
    )
if snapshot.limits.same_curve:
    st.info("平台规则：24 时段共用一条报价曲线。所有新策略遵循该限制。")
else:
    st.info("平台规则：允许不同时段采用不同曲线。自适应策略将逐时段生成五段报价。")
st.caption(
    f"机组 {len(snapshot.units)} 台 · {snapshot.period_num} 时段 · "
    f"负荷数据来源：{snapshot.forecast_source} · 市场类型：{snapshot.limits.market_type}"
)

unit_lookup = {u.unit_id: u for u in snapshot.units}
with st.form("strategy_lab_settings"):
    target_id = st.selectbox(
        "目标发电机组",
        tuple(unit_lookup),
        format_func=lambda key: f"{unit_lookup[key].name} · {key}",
    )
    columns = st.columns(3)
    max_markup = columns[0].number_input(
        "最高加价（相对运行成本参数）", min_value=0.0, value=100.0, step=10.0
    )
    markup_step = columns[1].number_input(
        "加价搜索步长", min_value=1.0, value=25.0, step=5.0
    )
    risk_aversion = columns[2].slider("风险厌恶系数", 0.0, 1.0, 0.35, 0.05)
    risk_cols = st.columns(3)
    demand_deviation = risk_cols[0].slider(
        "负荷波动范围", 0.0, 0.30, 0.05, 0.01
    )
    peer_deviation = risk_cols[1].slider(
        "竞争报价波动范围", 0.0, 0.30, 0.05, 0.01
    )
    tail_fraction = risk_cols[2].slider(
        "下行情景概率占比", 0.05, 1.0, 0.25, 0.05
    )
    run = st.form_submit_button("比较所有报价策略", type="primary")

if not run:
    st.stop()
if max_markup / markup_step > 18:
    st.error("最多搜索 20 个不同的加价档位，请增大步长。")
    st.stop()
markups = [round(i * markup_step, 8) for i in range(int(max_markup / markup_step) + 1)]
if not markups or markups[-1] < max_markup - 1e-6:
    markups.append(float(max_markup))

try:
    with st.spinner("正在本地计算策略与风险情景"):
        comparison = compare_strategies(
            snapshot,
            target_id,
            markups=markups,
            scenarios=stress_grid(
                demand_deviation=demand_deviation,
                peer_price_deviation=peer_deviation,
            ),
            risk_aversion=risk_aversion,
            tail_fraction=tail_fraction,
        )
except ValueError as exc:
    st.error(f"策略对比未完成：{exc}")
    st.stop()

best = comparison.recommended
baseline = comparison.baseline
st.subheader("研究结果")
m = st.columns(4)
m[0].metric("推荐策略", best.name)
m[1].metric("模型预期利润", f"{best.expected_profit:,.2f}")
m[2].metric("下行平均利润", f"{best.downside_profit:,.2f}")
m[3].metric("测试策略数量", f"{comparison.evaluated}")

st.caption(
    "评分 = (1 - 风险厌恶系数) × 情景加权平均利润 + "
    "风险厌恶系数 × 最差概率区间平均利润。"
    "仅在全部情景都能满足模拟负荷的方案中挑选推荐。"
)
st.dataframe(
    pd.DataFrame(
        {
            "策略": row.name,
            "模拟期望利润": row.expected_profit,
            "下行利润": row.downside_profit,
            "最差利润": row.worst_profit,
            "期望中标MWh": row.expected_accepted_mwh,
            "可行情景概率": row.feasible_probability,
            "风险综合得分": row.score,
        }
        for row in comparison.ranked
    ),
    use_container_width=True,
    hide_index=True,
)
difference = best.expected_profit - baseline.expected_profit
st.info(
    f"相对历史报价的本地代理模型期望利润变化：{difference:+,.2f}。"
    "这不是实际 PMSS 改报后的增益，不能据此直接提交报价。"
)

st.subheader("推荐24小时分段量价表")
blocks = [
    {
        "起始时段": period.start_period,
        "结束时段": period.end_period,
        "段号": number,
        "起始MW": segment.start_power,
        "结束MW": segment.end_power,
        "报价": segment.price,
    }
    for period in best.periods
    for number, segment in enumerate(period.segments, 1)
]
st.dataframe(pd.DataFrame(blocks), use_container_width=True, hide_index=True)

normal = next(
    (case for case in best.scenarios if "demand x1.00 / peer bid x1.00" == case.name),
    best.scenarios[0],
)
st.subheader("逐时段模拟结果")
st.caption(f"展示情景：{normal.name}，属于独立的合成压力情景。")
hourly = pd.DataFrame(
    {
        "时段": row.period,
        "本地模拟出清价": row.clearing_price,
        "本地模拟中标MW": row.accepted_mw,
        "本地模拟利润": row.profit,
    }
    for row in normal.hours
)
st.line_chart(hourly.set_index("时段")[["本地模拟利润"]])
st.dataframe(hourly, use_container_width=True, hide_index=True)

review = {
    "notice": "OFFLINE SURROGATE ONLY - REVIEW FILE, NOT A PMSS SUBMISSION",
    "strategy": best.name,
    "unitId": target_id,
    "marketTypeAtom": snapshot.limits.market_type,
    "forecastSource": snapshot.forecast_source,
    "periods": [
        {
            "startPeriod": period.start_period,
            "endPeriod": period.end_period,
            "segmentDatas": [
                {
                    "segmentOrder": i,
                    "startPower": seg.start_power,
                    "endPower": seg.end_power,
                    "price": seg.price,
                }
                for i, seg in enumerate(period.segments, 1)
            ],
        }
        for period in best.periods
    ],
}
st.download_button(
    "下载离线报价审核 JSON（不提交 PMSS）",
    data=json.dumps(review, ensure_ascii=False, indent=2).encode("utf-8"),
    file_name="powerbid_strategy_review.json",
    mime="application/json",
)
st.warning(
    "约束边界：目前没有纳入实际电网潮流、节点电价、机组启停、爬坡、"
    "最小连续开停机时间、启动成本与真实结算规则。"
    "最小技术出力仅被用作报价段分界，不构成出清可行性证明。"
)
