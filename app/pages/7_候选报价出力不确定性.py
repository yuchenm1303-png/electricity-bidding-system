"""Independent local candidate bid MW-envelope explorer (not PMSS simulation)."""
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

from powerbid.candidate_dispatch_uncertainty import (  # noqa: E402
    assess_candidate_dispatch_uncertainty,
)
from powerbid.network_dispatch import network_from_dict  # noqa: E402
from powerbid.network_strategy import verify_network_inputs  # noqa: E402
from powerbid.pmss_integration import BidSegment, snapshot_from_pmss  # noqa: E402

st.set_page_config(page_title="PowerBid · 候选报价不确定性", layout="wide")
st.title("候选报价 · 中标出力不确定性")
st.caption("对新的当前规则内报价，计算每小时在相同最低申报成本下可能出现的中标量范围")
st.warning(
    "这是基于历史其他机组报价和已核实DC网络的独立离线研究，不是未来PMSS"
    "实际中标区间，也不包含机组启停、备用、AC损耗或真实结算。"
    "不会向老师平台发送任何报价或执行请求。"
)
st.info(
    "当多个机组报价相同或出清解不唯一时，单独一个LP解可能显著误导。"
    "这里保留当日其他机组原始申报不变，研究您新报价的出力下界和上界。"
)

file = st.file_uploader("上传脱敏 PMSS 历史研究快照（需含 dcNetwork）", type=["json"])
if file is None:
    st.stop()
try:
    if file.size > 4 * 1024 * 1024:
        raise ValueError("单份脱敏快照不能超过4MiB")
    raw = json.loads(file.getvalue().decode("utf-8"))
    if not isinstance(raw, dict) or raw.get("historicalBacktestOnly") is not True:
        raise ValueError("仅允许明确标记 historicalBacktestOnly 的历史研究资料")
    allowed = {
        "unitTree", "unitBids", "marketSystem", "demandForecastMw",
        "forecastSource", "historicalBacktestOnly", "caseDate", "dcNetwork",
        "results", "loadSourceKind", "loadNodeCount",
    }
    if set(raw) - allowed:
        raise ValueError("数据文件含未纳入脱敏白名单的字段")
    stack = [raw]
    count = 0
    while stack:
        item = stack.pop()
        count += 1
        if count > 100_000:
            raise ValueError("JSON 数据过大或嵌套异常")
        if isinstance(item, dict):
            for key, val in item.items():
                lowered = key.lower().replace("_", "").replace("-", "")
                if any(tag in lowered for tag in (
                    "cookie", "token", "secret", "password", "session",
                    "privatekey", "authorization", "csrf",
                )):
                    raise ValueError("快照中包含认证信息字段，请先使用服务器白名单导出器")
                stack.append(val)
        elif isinstance(item, list):
            stack.extend(item)
    snapshot = snapshot_from_pmss(
        unit_tree=raw["unitTree"],
        unit_bids=raw["unitBids"],
        market_system=raw["marketSystem"],
        demand_forecast_mw=raw["demandForecastMw"],
        forecast_source=raw["forecastSource"],
    )
    network = network_from_dict(raw["dcNetwork"])
    verify_network_inputs(snapshot, network, snapshot.units[0].unit_id)
    if len(network.buses) > 60 or len(network.lines) > 90:
        raise ValueError("当前交互研究界面最多接受60节点、90线路")
except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
    st.error(f"读取文件失败：{exc}")
    st.stop()

st.caption(
    f"已核实节点{len(network.buses)}个、线路{len(network.lines)}条、"
    f"机组{len(snapshot.units)}台。负荷来源：{network.demand_source}"
)
with st.form("dc_candidate_dispatch_range"):
    target = st.selectbox(
        "待报价机组",
        [unit.unit_id for unit in snapshot.units],
        format_func=lambda uid: f"{snapshot.unit(uid).name} · {uid}",
    )
    u = snapshot.unit(target)
    lower = max(0.0, snapshot.limits.price_floor or 0.0)
    upper = min(
        10000.0,
        snapshot.limits.price_ceiling
        if snapshot.limits.price_ceiling is not None else 10000.0,
    )
    if upper < lower:
        st.error("当前市场价格上下限不一致")
        st.stop()
    price = st.number_input(
        "新报价价格（单段覆盖全机组上限；仅研究）",
        min_value=float(lower), max_value=float(upper),
        value=float(max(lower, min(upper, u.running_cost))),
        step=1.0,
    )
    threshold = st.number_input(
        "认定分配存在明显歧义的每小时出力差阈值（MW）",
        min_value=0.0, max_value=float(u.capacity_mw),
        value=float(min(1.0, u.capacity_mw)), step=0.5,
    )
    st.caption(
        "单段报价只是为了直观测试同价/不同价情况下的中标区间。"
        "系统内部同样支持1至5段候选报价，必须遵守当前规则。"
    )
    acknowledged = st.checkbox(
        "我理解这些区间是简化DC模型中等成本解的敏感性范围，不是老师PMSS对新报价的承诺",
        value=False,
    )
    submitted = st.form_submit_button("计算24小时出力不确定性", type="primary")
if not submitted:
    st.stop()
if not acknowledged:
    st.error("请先确认研究模型的边界和适用条件。")
    st.stop()

try:
    with st.spinner("正在求解24小时机组可中标出力下界及上界"):
        report = assess_candidate_dispatch_uncertainty(
            snapshot, network, target,
            (BidSegment(0.0, u.capacity_mw, price),),
            ambiguity_threshold_mw=threshold,
        )
except (ValueError, RuntimeError, TypeError) as exc:
    st.error(f"离线出力范围求解失败，不能生成该候选的区间结论：{exc}")
    st.stop()

metrics = st.columns(4)
metrics[0].metric("最小累计中标量", f"{report.minimum_accepted_mwh:,.1f} MWh")
metrics[1].metric("最大累计中标量", f"{report.maximum_accepted_mwh:,.1f} MWh")
metrics[2].metric("普通LP累计中标量", f"{report.default_lp_accepted_mwh:,.1f} MWh")
metrics[3].metric("出力分配不唯一的小时", f"{report.ambiguous_hours}/24")
st.caption(
    "不同小时的最优成本面独立计算；这不是24小时机组组合与爬坡约束联合可行的区间。"
)

rows = pd.DataFrame([
    {
        "小时": hour.period,
        "最小中标MW": hour.minimum_accepted_mw,
        "普通LP中标MW": hour.default_lp_accepted_mw,
        "最大中标MW": hour.maximum_accepted_mw,
        "同成本出力宽度MW": hour.range_width_mw,
    }
    for hour in report.hours
])
st.line_chart(
    rows.set_index("小时")[["最小中标MW", "普通LP中标MW", "最大中标MW"]]
)
st.dataframe(rows, use_container_width=True, hide_index=True)
if report.ambiguous_hours:
    st.warning(
        "该候选存在同成本多解；不能只拿普通LP的一条中标轨迹当作确定预测。"
        "正式使用需要确认PMSS实际出清规则，并进行独立日期回测。"
    )
else:
    st.info(
        "在当前独立DC模型、原始同行报价与此阈值下，没有发现明显同成本中标量歧义。"
        "但这仍不等于已确认PMSS出清、真实节点价格或收益。"
    )
if report.original_peer_units_over_current_price_rule:
    st.warning(
        "有历史同行机组已保存报价超出快照中的当前申报价格限制。"
        "该历史场景不能直接代表当前规则下的合法竞争环境。"
    )

st.download_button(
    "下载离线候选报价区间审核报告",
    data=json.dumps(asdict(report), ensure_ascii=False, indent=2).encode("utf-8"),
    file_name="powerbid_candidate_mw_uncertainty.json",
    mime="application/json",
)
