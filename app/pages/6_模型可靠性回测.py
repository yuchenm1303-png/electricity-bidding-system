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

from powerbid.expost_commitment_diagnostics import (  # noqa: E402
    replay_zero_output_restriction,
)
from powerbid.flow_error_attribution import (  # noqa: E402
    compare_dispatch_and_network_sources,
)
from powerbid.historical_ambiguity import audit_historical_optimal_ambiguity  # noqa: E402
from powerbid.historical_price_hypotheses import (  # noqa: E402
    audit_historical_price_caps,
)
from powerbid.historical_tiebreak_audit import audit_historical_tiebreaks  # noqa: E402
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
    raw_by_date = {}
    with st.spinner("正在按原始报价重新计算24小时DC电网出清并比较历史记录"):
        for uploaded in uploads:
            if uploaded.size > 4 * 1024 * 1024:
                raise ValueError("单个脱敏历史文件不得超过4MiB")
            source = json.loads(uploaded.getvalue().decode("utf-8"))
            checked = validate_historical_day(source)
            days.append(checked)
            raw_by_date[checked.case_date] = source
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

st.subheader("逐节点价格误差")
node_df = pd.DataFrame([
    {
        "节点 ID": item.element_id,
        "价格 MAE": item.metric.mae,
        "价格 RMSE": item.metric.rmse,
        "历史数据覆盖率": item.metric.coverage,
    }
    for item in selected_day.per_node
])
st.dataframe(
    node_df.sort_values("价格 MAE", ascending=False, na_position="last"),
    hide_index=True, use_container_width=True,
)

st.subheader("逐线路潮流幅值误差")
line_df = pd.DataFrame([
    {
        "线路 ID": item.element_id,
        "潮流绝对值 MAE (MW)": item.metric.mae,
        "潮流绝对值 RMSE (MW)": item.metric.rmse,
        "历史数据覆盖率": item.metric.coverage,
    }
    for item in selected_day.per_branch
])
if not line_df.empty:
    st.dataframe(
        line_df.sort_values("潮流绝对值 MAE (MW)", ascending=False, na_position="last"),
        hide_index=True, use_container_width=True,
    )
else:
    st.info("该网络没有可比较的线路历史数据，不能进行线路模型校准。")

st.subheader("误差归因对照：报价出清 vs 固定真实机组出力")
st.caption(
    "同一日、同一网架、相同支路观测：对比独立重新出清和固定PMSS真实发电量后"
    "进行DC潮流重算的误差。后者使用事后数据，只用于排查网架模型，"
    "绝不是未来报价的预测能力或实际盈利改善。"
)
with st.spinner("正在固定历史机组出力，重新计算DC网络潮流"):
    diagnostic = compare_dispatch_and_network_sources(raw_by_date[selected_day.case_date])
comparison = diagnostic.comparison
c1, c2, c3 = st.columns(3)
c1.metric(
    "独立报价出清潮流 MAE",
    "无观测" if comparison.independent_dispatch_flow_mae_mw is None
    else f"{comparison.independent_dispatch_flow_mae_mw:,.2f} MW",
)
c2.metric(
    "固定历史机组出力后潮流 MAE",
    "无观测" if comparison.observed_dispatch_flow_mae_mw is None
    else f"{comparison.observed_dispatch_flow_mae_mw:,.2f} MW",
)
c3.metric(
    "可比误差差值",
    "不可直接比较" if comparison.absolute_mae_difference_mw is None
    else f"{comparison.absolute_mae_difference_mw:+,.2f} MW",
)
if not comparison.same_observation_set:
    st.warning(
        "部分小时发电量缺失或不满足全网平衡，"
        "两种计算使用的样本不完全相同，不能直接用差值做结论。"
    )
else:
    st.info(
        "固定真实出力能帮助判断独立报价出清的误差是否更大，"
        "但不能证明差异完全由机组组合造成。"
        "仍需排查交流潮流、线路参数、分接头及PMSS报告口径。"
    )

fixed_lines = pd.DataFrame([
    {
        "线路ID": line.line_id,
        "固定真实出力潮流MAE(MW)": line.magnitude_mae_mw,
        "正方向偏差MAE(MW)": line.signed_mae_mw,
        "反方向偏差MAE(MW)": line.reversed_mae_mw,
        "有效时段数": line.observed_points,
        "DC潮流超过额定次数": line.modeled_limit_exceed_count,
    }
    for line in diagnostic.observed_dispatch.per_line
])
if not fixed_lines.empty:
    st.dataframe(
        fixed_lines.sort_values(
            "固定真实出力潮流MAE(MW)", ascending=False, na_position="last"
        ).head(20),
        hide_index=True, use_container_width=True,
    )

st.subheader("同成本多解诊断 · PMSS 历史中标能否构成本地最优解？")
st.caption(
    "采用同一天已提交的原始报价、固定网架和全部机组历史中标量。"
    "每小时额外求解机组独立最优范围及整组中标量的网络可行性、"
    "报价成本最优性；不预测新报价结果。"
)
with st.spinner("正在计算每小时同成本最优解空间（额外线性规划）"):
    ambiguity = audit_historical_optimal_ambiguity(
        raw_by_date[selected_day.case_date]
    )
    zero_stress = replay_zero_output_restriction(
        raw_by_date[selected_day.case_date]
    )
z1, z2, z3 = st.columns(3)
z1.metric(
    "存在多组近似等成本最优解的小时",
    f"{ambiguity.multiple_optima_hours}/{ambiguity.examined_hours}",
)
z2.metric(
    "老师实际全机组组合在本地最优成本面的小时",
    f"{ambiguity.observed_joint_model_optimal_hours}/"
    f"{ambiguity.observed_complete_hours}",
)
z3.metric(
    "各机组历史出力落在独立可行区间",
    f"{ambiguity.observed_individual_in_range}/"
    f"{ambiguity.observed_individual_evaluated}",
)
st.warning(
    "即使全部小时落在同一优化成本面，也只能说明原始报价数据在我们"
    "简化DC模型中存在一种等成本配置，不能证明两套市场出清规则相同，"
    "更不能证明节点电价或新报价利润预测准确。"
)
st.dataframe(
    pd.DataFrame([
        {
            "时段": hour.period,
            "出清出力唯一": "是" if hour.model_unique_allocation else "否",
            "最大单机组最优出力范围 MW": hour.max_individual_range_width_mw,
            "该小时实测出力齐全": hour.observed_unit_mw_count
            == ambiguity.distinct_units,
            "整组历史出力满足DC网架": hour.observed_jointly_feasible,
            "历史组合保持成本最优": hour.observed_on_model_optimal_face,
            "历史组合申报成本差额": hour.observed_bid_cost_gap,
        }
        for hour in ambiguity.hours
    ]),
    hide_index=True, use_container_width=True,
)
st.subheader("零出力状态敏感性：仅用于历史归因")
z4, z5, z6 = st.columns(3)
z4.metric(
    "历史零出力的机组×小时", str(zero_stress.observed_zero_unit_hours)
)
z5.metric(
    "原模型仍给零出力机组发电次数",
    str(zero_stress.baseline_positive_on_observed_zero_unit_hours),
)
z6.metric(
    "事后零出力约束可求解的小时",
    f"{zero_stress.paired_hours}/24",
)
st.caption(
    "施加事后零出力约束可能触发LP求解器选择另一组等成本最优出力。"
    "如果原始模型已经让这些机组发电量为零，改进并不能归因于机组启停规则。"
)
if zero_stress.paired_hours:
    st.write(
        "在相同可比小时中，机组中标 MAE："
        f"原模型 {zero_stress.baseline_paired_dispatch_mae_mw:.3f} MW；"
        f"事后约束 {zero_stress.masked_paired_dispatch_mae_mw:.3f} MW。"
        "后者使用了事后真实信息，禁止作为未来预测性能对外展示。"
    )

st.subheader("历史节点价格上限假设 · 原模型对偶电价 vs 报告价格")
st.caption(
    "此检查仅对历史原始报价的本地DC模型输出节点价作事后假设变换。"
    "不修改原始报价、实际电价、出清求解器或策略评分。"
    "假设1000对应当前申报上限；1001只来自这个历史数据的异常表现，"
    "不代表已证实PMSS存在1001的结算价格上限。"
)
with st.spinner("正在逐节点比较原始DC价格与两种假设上限"):
    price_study = audit_historical_price_caps(
        raw_by_date[selected_day.case_date],
        hypothetical_ceilings=(1000.0, 1001.0),
    )
st.dataframe(
    pd.DataFrame([
        {
            "对照方式": hypothesis.label,
            "观测节点×小时": hypothesis.observed_points,
            "节点价格MAE": hypothesis.mae,
            "RMSE": hypothesis.rmse,
            "完全匹配点数": hypothesis.matching_points,
            "相对原模型改善点数": hypothesis.improved_points_vs_uncapped,
            "相对原模型变差点数": hypothesis.worsened_points_vs_uncapped,
        }
        for hypothesis in price_study.hypotheses
    ]),
    hide_index=True, use_container_width=True,
)
st.dataframe(
    pd.DataFrame([
        {
            "小时": hour.period,
            "有效节点": hour.observed_points,
            "未处理DC价格MAE": hour.raw_mae,
            "未处理价格不吻合节点": hour.raw_mismatching_points,
            "未处理DC最大节点电价": hour.raw_peak_price,
            "PMSS历史最大节点电价": hour.observed_peak_price,
            "假设1000上限后MAE": hour.capped_mae_by_hypothesis[0],
            "假设1001上限后MAE": hour.capped_mae_by_hypothesis[1],
        }
        for hour in price_study.hours
    ]),
    hide_index=True, use_container_width=True,
)
if price_study.historically_exact_price_fit_for_any_hypothesis:
    st.warning(
        "至少一项输出变换完全拟合本日历史价格，但这仍是事后匹配！"
        "尤其在目前只有单个真实日期、且老师的报价上限与结算规则"
        "尚未独立核实的情况下，不允许自动套用到未来报价或收益计算。"
    )
st.info(
    "历史保存的最大原报价 "
    f"{price_study.maximum_price_in_saved_original_offers:g}；"
    "当前快照申报价格上限 "
    f"{price_study.price_ceiling_in_current_market_rule}。"
    "历史保存价格超当前规则不意味着当时违规，"
    "也不表示新报价可以突破当前申报上限。"
)

st.subheader("确定性并列最优分配 · 出清结果对机组排序是否敏感？")
st.caption(
    "以相同历史原始报价、相同DC网架与不变的最低报价成本为前提，"
    "依次比较：原始申报文件顺序、规范化机组与报价段顺序、"
    "机组ID正序优先和机组ID倒序优先。"
    "历史中标量仅用于事后测评，绝不用于选择预测规则。"
)
with st.spinner("正在验证多组相同主目标成本下的确定性次级分配"):
    tiebreak_study = audit_historical_tiebreaks(
        raw_by_date[selected_day.case_date]
    )
st.dataframe(
    pd.DataFrame([
        {"同成本出力方案": "原始报价输入顺序的标准LP解",
         "该日事后中标量MAE (MW)": tiebreak_study.source_order_baseline_mae_mw},
        {"同成本出力方案": "规范化报价段顺序的标准LP解",
         "该日事后中标量MAE (MW)": tiebreak_study.canonical_order_baseline_mae_mw},
        {"同成本出力方案": "机组ID正序优先",
         "该日事后中标量MAE (MW)": tiebreak_study.ascending_dispatch_mae_mw},
        {"同成本出力方案": "机组ID倒序优先",
         "该日事后中标量MAE (MW)": tiebreak_study.descending_dispatch_mae_mw},
    ]),
    hide_index=True, use_container_width=True,
)
tie_cols = st.columns(3)
tie_cols[0].metric(
    "不同顺序产生不同出力分配的小时",
    f"{tiebreak_study.hours_with_different_deterministic_allocations}/24",
)
tie_cols[1].metric(
    "最大全机组出力重新分配量",
    f"{tiebreak_study.maximum_total_allocation_difference_mw:,.2f} MW",
)
tie_cols[2].metric(
    "最大主目标申报成本偏差",
    f"{tiebreak_study.maximum_primary_bid_cost_increase:,.6f}",
)
st.dataframe(
    pd.DataFrame([
        {
            "小时": h.period,
            "原始顺序 LP MAE(MW)": h.source_order_baseline_mae_mw,
            "规范顺序 LP MAE(MW)": h.canonical_order_baseline_mae_mw,
            "正序优先 MAE(MW)": h.ascending_mae_mw,
            "倒序优先 MAE(MW)": h.descending_mae_mw,
            "正序/倒序出力绝对位移(MW)": h.ascending_vs_descending_total_mw_shift,
            "申报成本偏差": h.max_primary_cost_increase,
        }
        for h in tiebreak_study.hours
    ]),
    hide_index=True, use_container_width=True,
)
st.warning(
    "这里的排序规则完全是PowerBid为测试设计的固定假设，"
    "并未识别老师PMSS实际采用什么顺序。"
    "即使有规则在单日历史MAE更小，也不表示新报价回测通过。"
    "同时，无论如何更换原始LP最优出力，都不能直接把1001价格假设"
    "当作真实结算规则写入利润模型。"
)

report = {
    "notice": (
        "Historical original PMSS bids vs offline DC baseline ONLY. "
        "Never substitute this report for new-bid PMSS clearing results."
    ),
    "user_defined_thresholds": asdict(policy),
    "verdict": asdict(verdict),
    "days": [asdict(day) for day in sorted(days, key=lambda item: item.case_date)],
    "selected_day_attribution": asdict(diagnostic.comparison),
    "selected_day_optimal_face": asdict(ambiguity),
    "selected_day_price_hypotheses": asdict(price_study),
    "selected_day_deterministic_tiebreak": asdict(tiebreak_study),
    "selected_day_expost_zero_sensitivity": asdict(zero_stress),
    "selected_day_fixed_dispatch_lines": [
        asdict(line) for line in diagnostic.observed_dispatch.per_line
    ],
}
st.download_button(
    "下载不含平台凭证的回测指标报告",
    data=json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
    file_name="powerbid_historical_model_validation.json",
    mime="application/json",
)
