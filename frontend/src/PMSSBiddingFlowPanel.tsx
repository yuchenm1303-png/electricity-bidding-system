import { useState } from "react";
import { ArrowRight, Download, ShieldCheck } from "lucide-react";
import type { PMSSInspection, PMSSNetworkRank, PMSSOptimization } from "./types";
import {
  proposalAuditDocument, proposalFromNetworkRank, proposalFromSurrogate,
  type PMSSBidProposal,
} from "./pmssBiddingFlow";

type Props = {
  inspection: PMSSInspection;
  target: string;
  analysis: PMSSOptimization | null;
  rankResult: PMSSNetworkRank | null;
  proposal: PMSSBidProposal | null;
  manualReviewReady: boolean;
  pending: boolean;
  onImport: () => void;
  onOptimize: () => void;
  onRank: () => void;
  onChoose: (proposal: PMSSBidProposal) => void;
};

function saveProposal(proposal: PMSSBidProposal) {
  const blob = new Blob([JSON.stringify(proposalAuditDocument(proposal), null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "powerbid_bid_candidate_REVIEW_ONLY.json";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function PMSSBiddingFlowPanel({
  inspection, target, analysis, rankResult, proposal, manualReviewReady, pending,
  onImport, onOptimize, onRank, onChoose,
}: Props) {
  const [error, setError] = useState("");
  const surrogate = analysis?.target_unit_id === target ? analysis : null;
  const network = rankResult?.target_unit_id === target ? rankResult : null;
  const hasLoad = inspection.load_mw.length === 24 &&
    inspection.load_mw.every(x => Number.isFinite(x) && x >= 0);
  const hasStudy = !!(surrogate || network);
  const chosen = proposal?.targetUnitId === target &&
    proposal.caseDate === inspection.case_date ? proposal : null;
  const steps = [
    ["01", "选择 PMSS 案例", true],
    ["02", "核对负荷预测来源", hasLoad],
    ["03", "风险与策略优化", hasStudy],
    ["04", "确认五段报价", !!chosen],
    ["05", "人工提交老师平台", false],
    ["06", "导入出清结果", manualReviewReady],
    ["07", "收益与误差复盘", manualReviewReady],
  ] as const;

  const choose = (fn: () => PMSSBidProposal) => {
    try {
      setError("");
      onChoose(fn());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法确认报价曲线");
    }
  };

  return <div className="pmss-panel" aria-label="PMSS 报价策略闭环">
    <div className="pmss-panel-head">
      <div>
        <small>POWERBID / BID DECISION WORKFLOW</small>
        <h3>报价决策 · 七步工作流程</h3>
        <p>案例 → 负荷输入 → 策略排序 → 五段曲线 → 老师平台人工操作 → 导入结果 → 描述性复盘。</p>
      </div>
      <span className="pmss-state-label"><ShieldCheck size={14}/> 仅本地计算，不提交</span>
    </div>
    <div className="pmss-process-steps" aria-label="七步报价状态">
      {steps.map(([number, label, completed], index) =>
        <span key={number} className={completed ? "complete" : index === (chosen ? 4 : hasStudy ? 3 : hasLoad ? 2 : 1) ? "current" : ""}>
          <b>{number}</b> {label}
        </span>
      )}
    </div>
    <div className="pmss-summary">
      <article className="pmss-metric">
        <span>当前 PMSS 研究案例</span><strong>{inspection.case_date || "未标注日期"}</strong>
        <small>{target || "尚未选择机组"} · {inspection.units.length} 台机组</small>
      </article>
      <article className="pmss-metric">
        <span>24小时负荷输入</span><strong>{hasLoad ? "24 / 24" : "待补齐"}</strong>
        <small>{inspection.forecast_source || "未注明来源"} · {inspection.load_source_kind || "来源类型待核查"}</small>
      </article>
      <article className="pmss-metric">
        <span>策略研究环境</span>
        <strong>{inspection.dc_grid_available ? "DC 网络 + 单区域" : "单区域近似"}</strong>
        <small>历史数据拟合与新报价验证必须分别解释</small>
      </article>
    </div>
    <p className="pmss-footnote">
      预测环节目前复用案例携带的 24 小时负荷序列，尚未接入独立负荷预测模型；
      <strong>历史负荷、历史申报价和人为扰动不是未来真实预测</strong>。
      {inspection.historical_only
        ? " 本次是历史案例研究，历史出清仅用于原报价回测。"
        : " 本案例未标记为历史研究；当前人工结果复盘接口只接受已标记的历史研究案例。"}
      当前推荐方案为 24 小时共用一条最多五段曲线。
    </p>
    <div className="pmss-toolbar">
      <p>先确认案例、日期、目标机组及负荷来源，再复用已有两种策略引擎。</p>
      <button type="button" onClick={onImport} disabled={pending}>更换案例</button>
      <button className="pmss-run-button" type="button" onClick={onOptimize}
        disabled={pending || !target || !hasLoad}>单区域五段优化 <ArrowRight size={15}/></button>
      <button className="pmss-run-button" type="button" onClick={onRank}
        disabled={pending || !target || !inspection.dc_grid_available || !inspection.historical_only}>
        网络风险排序 <ArrowRight size={15}/>
      </button>
    </div>
    {hasStudy && <div className="pmss-toolbar">
      <p>选择实际要用于人工核对的方案（选择后固定对应案例及机组，切换输入会使选择失效）。</p>
      {surrogate && <button type="button" disabled={pending}
        onClick={() => choose(() => proposalFromSurrogate(inspection, surrogate))}>
        采用单区域推荐
      </button>}
      {network && <button type="button" disabled={pending}
        onClick={() => choose(() => proposalFromNetworkRank(inspection, network))}>
        采用网络风险排序第 1 名
      </button>}
    </div>}
    {error && <div className="pmss-error" role="alert">{error}</div>}
    {chosen && <>
      <div className="pmss-result-toolbar">
        <h4>已选候选方案 · {chosen.strategyLabel}</h4>
        <button type="button" onClick={() => saveProposal(chosen)}>
          <Download size={15}/> 下载本地审核 JSON
        </button>
      </div>
      <div className="pmss-table-scroll"><table className="pmss-table">
        <thead><tr><th>段号</th><th>起始 MW</th><th>结束 MW</th><th>申报价格</th></tr></thead>
        <tbody>{chosen.segments.map((s, index) =>
          <tr key={index}><td>{index + 1}</td><td>{s.start_power}</td>
            <td>{s.end_power}</td><td>{s.price}</td></tr>)}</tbody>
      </table></div>
      <p className="pmss-footnote">
        已选方案仅是本地研究建议，不是 PMSS 已接收的订单。
        {inspection.dc_grid_available
          ? " 可在下方运行现有 DC 网络约束复算后再人工核对。"
          : " 缺少经验证的电网参数，不能宣称已通过网络潮流验证。"}
        人工提交后导入的结果仍只被标记为操作者声明关联，不具有平台签名证据。
      </p>
    </>}
    {!chosen && <p className="pmss-footnote">
      尚未确定候选报价。单区域优化与网络排名的结果互不覆盖；
      必须明确选择一条曲线，之后才能进入人工提交和结果对照。
    </p>}
    {manualReviewReady && <p className="pmss-footnote">
      已完成一次人工关联的结果比较：中标量误差可作描述性复盘，
      income 字段不能直接称为净利润，关联不构成新报价因果验证。
    </p>}
  </div>;
}
