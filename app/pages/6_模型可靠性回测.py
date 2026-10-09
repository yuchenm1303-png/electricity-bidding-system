"""Read-only multi-day PMSS historical model validation; no platform actions."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from powerbid.historical_validation import (  # noqa: E402
    ValidationPolicy,
    judge_historical_model,
    validate_historical_day,
)

st.set_page_config(page_title="PowerBid · 模型可靠性回测", layout="wide")
st.title("模型可靠性回测 · PMSS 历史案例")
st.caption("按日期验证原始报价的 DC 出清误差，隔离历史校准和未来推荐")
st.warning(
    "本工具不向老师 PMSS 提交报价、不执行平台出清，也不声称重现平台结算。"
    "即使历史基线符合用户设定的误差阈值，也不能证明新报价在 PMSS 中盈利。"
)
st.info(
    "另一窗口已经接通真实 PMSS 39节点电网的只读导出。"
    "本页面需要同一天的脱敏快照同时包含 dcNetwork 与 results，"
    "不同日期的历史快照要分别导出，不可把同一天复制多份冒充独立样本。"
)

uploads = st.file_uploader(
    "选择 1–10 个不同日期的 PMSS 脱敏历史快照（JSON）",
    type=["json"], accept_multiple_files=True,
    key="powerbid_multiple_historical_days",
)
with st.form("historic_model_acceptance"):
    st.markdown("**由研究人员明确设定可接受误差，而非软件臆造的行业标准**")
    a, b, c = st.columns(3)
    max_unit_mae = a.number_input(
        "单机组中标量 MAE 上限（MW）",
        min_value=0.0, value=25.0, step=5.0,
    )
    max_node_mae = b.number_input(
        "节点电价 MAE 上限（与 PMSS 价格同单位）",
        min_value=0.0, value=50.0, step=10.0,
    )
    min_coverage = c.slider(
        "每类历史结果最低覆盖率", min_value=0.50,
        max_value=1.0, value=0.95, step=0.01,
    )
    d, e = st.columns(2)
    min_days = d.number_input(
        "最少不同历史日期", min_value=3, max_value=20, value=3, step=1,
    )
    holdout = e.number_input(
        "保留最近几天作为完全独立验证集",
        min_value=1, max_value=5, value=1, step=1,
    )
    acknowledged = st.checkbox(
        "我确认误差阈值是研究假设，且不能将历史基线验证当成新报价真实 PMSS 反馈",
        value=False,
    )
    started = st.form_submit_button("开始历史模型验证", type="primary")

if not started:
    st.stop()
if not uploads or len(uploads) > 10:
    st.error("请上传 1 至 10 个不同日期的已脱敏 PMSS 历史案例。")
    st.stop()
if not acknowledged:
    st.error("请确认模型结果的适用范围。")
    st.stop()
try:
    policy = ValidationPolicy(
        max_unit_dispatch_mae_mw=float(max_unit_mae),
        max_nodal_price_mae=float(max_node_mae),
        min_coverage=float(min_coverage),
        min_distinct_dates=int(min_days),
        holdout_dates=int(holdout),
    )
    days = []
    with st.spinner("正在按原始报价重新计算24小时DC电网出清并比较历史记录"):
        for uploaded in uploads:
            if uploaded.size > 4 * 1024 * 1024:
                raise ValueError("单个脱敏历史文件不得超过4MiB")
            source = json.loads(uploaded.getvalue().decode("utf-8"))
            days.append(validate_historical_day(source))
        verdict = judge_historical_model(days, policy)
except (ValueError, TypeError, KeyError, UnicodeDecodeError, RuntimeError) as exc:
    st.error(f"历史回测被拒绝：{exc}")
    st.stop()

st.subheader("模型诊断结果")
if verdict.status == "NOT_VALIDATED":
    st.error(
        "当前历史证据不足，或模型误差/数据覆盖率未满足研究人员提供的门槛。"
        "不要把该代理模型输出标注为可靠报价推荐。"
    )
else:
    st.success(
        "在所选历史案例及用户定义的误差门槛内，原始报价基线通过留出集检查。"
        "这不等于未来新报价已通过 PMSS 验证。"
    )
for reason in verdict.reasons:
    st.write(f"• {reason}")

metrics = st.columns(4)
metrics[0].metric("历史日期", f"{verdict.evidence_days} 天")
metrics[1].metric(
    "留出集发电量 MAE",
    "数据不足" if verdict.holdout_unit_mae is None
    else f"{verdict.holdout_unit_mae:,.2f} MW",
)
metrics[2].metric(
    "留出集节点电价 MAE",
    "数据不足" if verdict.holdout_nodal_price_mae is None
    else f"{verdict.holdout_nodal_price_mae:,.2f}",
)
metrics[3].metric("线路潮流覆盖率", f"{verdict.flow_coverage:.1%}")
st.caption(
    "留出集日期：" + "、".join(verdict.holdout_case_dates) +
    "；线路潮流使用绝对值比较，避免未经确认的支路方向约定影响结论。"
)

st.subheader("逐日期误差")
daily = pd.DataFrame([
    {
        "日期": day.case_date,
        "机组中标量 MAE (MW)": day.unit_dispatch.mae,
        "机组中标数据覆盖率": day.unit_dispatch.coverage,
        "全网节点电价 MAE": day.nodal_price.mae,
        "节点电价数据覆盖率": day.nodal_price.coverage,
        "线路潮流绝对值 MAE (MW)": day.line_flow_abs.mae,
        "线路潮流覆盖率": day.line_flow_abs.coverage,
        "最大单小时机组误差均值": day.max_hourly_dispatch_mae,
        "最大单小时电价误差均值": day.max_hourly_lmp_mae,
    }
    for day in sorted(days, key=lambda item: item.case_date)
])
st.dataframe(daily, hide_index=True, use_container_width=True)

selected_day = st.selectbox(
    "查看单日各机组中标偏差",
    sorted(days, key=lambda item: item.case_date),
    format_func=lambda day: day.case_date,
)
units = pd.DataFrame([
    {
        "机组ID": item.unit_id,
        "出力 MAE (MW)": item.dispatch.mae,
        "出力 RMSE (MW)": item.dispatch.rmse,
        "历史数据覆盖率": item.dispatch.coverage,
    }
    for item in selected_day.per_unit
])
st.dataframe(units, hide_index=True, use_container_width=True)

report = {
    "notice": (
        "Historical original PMSS bids vs offline DC baseline ONLY. "
        "Never substitute this report for new-bid PMSS clearing results."
    ),
    "user_defined_thresholds": asdict(policy),
    "verdict": asdict(verdict),
    "days": [asdict(day) for day in sorted(days, key=lambda item: item.case_date)],
}
st.download_button(
    "下载不含平台凭证的回测指标报告",
    data=json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
    file_name="powerbid_historical_model_validation.json",
    mime="application/json",
)
