import { useState, type ChangeEvent } from "react";
import { Activity, ShieldCheck, UploadCloud } from "lucide-react";
import { inspectPMSSHoldoutReport } from "./api";
import { numeric, type PMSSHoldoutReview } from "./types";

const statusTitles: Record<PMSSHoldoutReview["status"], string> = {
  TRAINING_GUARD_BLOCKED: "训练期门槛未通过 · 保留普通LP研究参照",
  HOLDOUT_DETERIORATION_OBSERVED: "留出日出现恶化 · 不得外推",
  DESCRIPTIVE_ONLY_INSUFFICIENT_EXTERNAL_VALIDATION: "描述性研究 · 仍缺独立验证",
};
const label: Record<string, string> = {
  canonical_lp: "规范化普通 LP",
  unit_id_ascending: "机组ID正序",
  unit_id_descending: "机组ID倒序",
};
const reason: Record<string, string> = {
  CANONICAL_ALREADY_TRAINING_BEST: "训练最优本来就是普通LP",
  TRAINING_OFFER_DIVERSITY_LT_2: "训练日报价曲线缺乏多样性",
  POOLED_TRAINING_IMPROVEMENT_BELOW_THRESHOLD: "训练总体改善未达到预先门槛",
  NOT_EVERY_TRAINING_DAY_IMPROVES_MATERIALLY: "并非每个训练日均有足够改善",
};

export function PMSSHoldoutGatePanel() {
  const [file, setFile] = useState("");
  const [result, setResult] = useState<PMSSHoldoutReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target.files?.[0];
    event.target.value = "";
    setFile("");
    setResult(null);
    setError("");
    if (!input) return;
    if (input.size > 120_000) {
      setError("仅支持不超过120KB的匿名留出聚合报告；不要上传原始PMSS快照。");
      return;
    }
    setBusy(true);
    try {
      const json: unknown = JSON.parse(await input.text());
      if (!json || Array.isArray(json) || typeof json !== "object") {
        throw new Error("需要只包含匿名历史回测汇总的JSON对象");
      }
      const reply = await inspectPMSSHoldoutReport(json as Record<string, unknown>);
      if (reply.liveBidAllowed !== false ||
          reply.pmssCounterfactualValidated !== false ||
          reply.profitForecastValidated !== false ||
          reply.sourceAuthenticatedByThisReport !== false ||
          reply.statisticalConfidenceEstablished !== false ||
          reply.researchOnly !== true ||
          reply.historicalOriginalBidsOnly !== true) {
        throw new Error("报告未满足历史研究不可实盘使用的安全条件");
      }
      setFile(input.name);
      setResult(reply);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "历史研究报告审核失败");
    } finally {
      setBusy(false);
    }
  }

  return <section className="pmss-panel" aria-label="历史留出规则可靠性">
    <div className="pmss-panel-head">
      <div>
        <small>RESEARCH / CHRONOLOGICAL HOLDOUT</small>
        <h3>历史分配规则 · 跨日期可靠性审核</h3>
        <p>导入本地脚本生成的匿名留出报告。分别检查训练集最优规则和训练阶段锁定的保守参照，
          统计第三天是否恶化、是否重复训练日报价。这里不会上传原始报价或机组出力明细。</p>
      </div>
      <span className="pmss-state-label"><ShieldCheck size={14}/> 只读 · 不可用于实盘</span>
    </div>
    <div className="pmss-controls">
      <label>匿名原始报价留出报告 JSON
        <input type="file" accept=".json,application/json" disabled={busy}
          onChange={event => void load(event)}
          aria-label="导入PowerBid匿名历史留出报告"/>
      </label>
    </div>
    <p className="pmss-footnote">
      <UploadCloud size={14}/> 请使用 scripts/report_pmss_tiebreak_holdout.py
      在有权限的可信环境生成报告；不要导入原始机组表、Cookie或老师平台抓包数据。
    </p>
    {busy && <p className="pmss-footnote" role="status">正在核对逐日聚合误差与训练规则…</p>}
    {error && <div className="pmss-error" role="alert">{error}</div>}
    {result && <>
      <p className="pmss-footnote">已核对文件：{file}。仅验证匿名报告内部一致性，无法独立认证真实PMSS来源。</p>
      <div className="pmss-error" role="status">
        {statusTitles[result.status]}。不代表实际老师平台的排序规则已被发现，
        也不能据此预测新报价收益。
      </div>
      <div className="pmss-summary">
        <article className="pmss-metric">
          <span>训练集最低误差规则</span>
          <strong>{label[result.trainingWinner] ?? "未知规则"}</strong>
          <small>{result.trainingDates.join("、")} · {result.distinctTrainingBidCurves}套不同原报价</small>
        </article>
        <article className="pmss-metric">
          <span>训练时锁定的保守参照</span>
          <strong>{label[result.lockedConservativeComparator] ?? "未知规则"}</strong>
          <small>{result.trainingGuardPassed ? "通过训练门槛" : "训练门槛未通过，采用普通LP参照"}</small>
        </article>
        <article className="pmss-metric">
          <span>留出日保守参照相对普通LP</span>
          <strong>{numeric(result.conservativeHoldoutDeltaMaeMw, 3)} MW</strong>
          <small>负数为改善，正数为恶化；不代表真实市场收益</small>
        </article>
      </div>
      <div className="pmss-table-scroll">
        <table className="pmss-table">
          <thead><tr><th>原报价留出研究方案</th><th>留出日中标量 MAE</th><th>相对普通LP变化</th></tr></thead>
          <tbody>
            <tr><td>规范化普通LP</td>
              <td>{numeric(result.canonicalHoldoutMaeMw, 3)} MW</td><td>基准</td></tr>
            <tr><td>训练集最佳：{label[result.trainingWinner] ?? result.trainingWinner}</td>
              <td>{numeric(result.trainingWinnerHoldoutMaeMw, 3)} MW</td>
              <td>{numeric(result.trainingWinnerHoldoutDeltaMaeMw, 3)} MW</td></tr>
            <tr><td>训练审核后的保守参照：{label[result.lockedConservativeComparator] ?? result.lockedConservativeComparator}</td>
              <td>{numeric(result.conservativeHoldoutMaeMw, 3)} MW</td>
              <td>{numeric(result.conservativeHoldoutDeltaMaeMw, 3)} MW</td></tr>
          </tbody>
        </table>
      </div>
      <p className="pmss-footnote">
        <Activity size={14}/> 留出日期：{result.holdoutDates.join("、")}；
        复用训练日报价的留出日期：{result.holdoutDatesReusingTrainingOffers}/{result.holdoutDayCount}；
        保守参照单日最大恶化：{numeric(result.conservativeWorstSingleDayDeteriorationMaeMw, 3)} MW。
      </p>
      {!result.trainingGuardPassed && <p className="pmss-footnote">
        训练期未过门槛：{result.trainingGuardReasons.map(key => reason[key] ?? key).join("；")}。
        退回普通LP只是一种研究参照，不是预测提升或“零风险”证明。
      </p>}
      <p className="pmss-footnote">
        历史原报价重放 ≠ 新报价反事实出清。样本量仍不足以证明统计显著性，
        完整性检查 ≠ 独立平台来源认证；不提供真实出清、提交资格或利润承诺。
      </p>
    </>}
  </section>;
}
