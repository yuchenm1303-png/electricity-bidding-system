import { useState, type ChangeEvent } from "react";
import { Download, FileJson2, ShieldCheck, UploadCloud } from "lucide-react";
import { reviewManuallyImportedPMSSResult } from "./api";
import { csvExport, numeric, type PMSSManualClearingReview } from "./types";
import type { PMSSBidProposal } from "./pmssBiddingFlow";

/**
 * Workflow intentionally ends at a HUMAN handoff. We have no authorized PMSS
 * bid-write/clearing API. Uploaded data is never attributed to this proposal
 * unless an operator explicitly makes that UNVERIFIED assertion.
 */
export function PMSSManualClearingPanel({
  snapshot, caseDate, proposal, onReviewed,
}: {
  snapshot: Record<string, unknown>;
  caseDate: string;
  proposal: PMSSBidProposal;
  onReviewed?: (review: PMSSManualClearingReview | null) => void;
}) {
  const [confirmation, setConfirmation] = useState(false);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState("");
  const [error, setError] = useState("");
  const [review, setReview] = useState<PMSSManualClearingReview | null>(null);

  function exportEntryTable() {
    // The local solver uses the SAME curve at each hour. A CSV with 24*5
    // rows is for human transcription and checking, NEVER direct submission.
    const rows = Array.from({length: 24}, (_, hour) =>
      proposal.segments.map((segment, i) => [
        hour + 1, i + 1, segment.start_power, segment.end_power, segment.price,
      ]),
    ).flat();
    csvExport(
      "powerbid_manual_24h_five_segment_REVIEW_ONLY.csv",
      ["时段(1-24)", "段号(1-5)", "起始出力MW", "结束出力MW", "报价", "说明"],
      rows.map(row => [...row, "24时段共用曲线-仅供人工核对"]),
    );
  }

  async function loadResult(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target.files?.[0];
    event.target.value = "";
    setFile("");
    setReview(null);
    onReviewed?.(null);
    setError("");
    if (!input) return;
    if (!confirmation) {
      setError("请先确认你已在老师平台人工提交本次报价，并明确选择对应的出清案例。");
      return;
    }
    if (input.size > 700_000) {
      setError("出清文件不能超过700KB，只导入脱敏的老师出清结果，不要上传凭据或抓包记录。");
      return;
    }
    setBusy(true);
    try {
      const data: unknown = JSON.parse(await input.text());
      if (!data || typeof data !== "object" || Array.isArray(data)) {
        throw new Error("出清结果必须是带案例日期的 JSON 对象");
      }
      const outer = data as Record<string, unknown>;
      const dated = outer.caseDate;
      const results = outer.results ?? outer;
      if (typeof dated !== "string" || !results || typeof results !== "object"
          || Array.isArray(results)) {
        throw new Error("需包含 caseDate 和 results（或同级 unitResults）字段");
      }
      if (dated !== caseDate) {
        throw new Error("出清文件日期与当前研究案例不同，请重新选择正确的结果");
      }
      const compared = await reviewManuallyImportedPMSSResult(
        snapshot, proposal.targetUnitId, proposal.segments,
        dated, results as Record<string, unknown>, true,
      );
      if (compared.pmss_write_performed !== false ||
          compared.pmss_clearing_executed !== false ||
          compared.teacher_result_authenticated !== false ||
          compared.candidate_bid_causality_verified !== false) {
        throw new Error("服务器未正确声明数据关联与出清来源的限制");
      }
      setReview(compared);
      onReviewed?.(compared);
      setFile(input.name);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "出清结果检查失败");
    } finally {
      setBusy(false);
    }
  }

  return <div className="pmss-panel" aria-label="报价至老师出清结果的人工交接">
    <div className="pmss-panel-head">
      <div>
        <small>05-07 / MANUAL RESULT HANDOFF</small>
        <h3>报价与老师出清结果 · 人工交接</h3>
        <p>先在 PowerBid 检查并导出五段报价建议；经老师授权，在其平台人工确认提交及执行课程规定的出清流程；最后把同日的脱敏出清结果导回本页面。</p>
      </div>
      <span className="pmss-state-label"><ShieldCheck size={14}/> 未启用自动提交</span>
    </div>
    <div className="pmss-process-steps" aria-label="人工出清交接流程">
      <span className="complete"><b>01</b> 已生成报价</span>
      <span className="current"><b>02</b> 核对并导出</span>
      <span><b>03</b> 老师平台人工操作</span>
      <span className={review ? "complete" : ""}><b>04</b> 导入并对比</span>
    </div>
    <div className="pmss-privacy">
      <FileJson2 size={17}/>
      当前机组 {proposal.targetUnitId} · {caseDate || "日期未标明"} ·
      <strong> 1–24 时段使用同一条五段曲线</strong>，并不是每小时独立优化的24条曲线。
      请使用上方「下载审核 JSON」记录分段、价格和 MW 边界。
      该文件仅供人工核对，不是老师平台可直接提交的API报文。
    </div>
    <div className="pmss-toolbar">
      <p>需要逐时段核对时，可导出24×5行人工录入检查表。所有24小时重复同一曲线，不代表24个独立最优方案。</p>
      <button className="pmss-run-button" type="button" onClick={exportEntryTable}>
        <Download size={16}/> 导出24小时人工核对 CSV
      </button>
    </div>
    <p className="pmss-footnote">尚未取得老师平台报价写入和执行出清的授权接口，本页面不会替你保存报价或点击出清。
      人工提交前应由你核对该案例的五段规则、申报电量、价格上下限和老师规定的操作权限。</p>
    <div className="pmss-toolbar">
      <p>完成老师平台的相应操作后，导入同一案例日期的脱敏出清 JSON。
        支持包含 <code>caseDate</code> 与 <code>results</code> 的只读快照格式，或者包含
        <code>caseDate</code>、<code>marketTypeAtom</code>、<code>periodNum</code>、
        <code>unitResults</code> 的结果文件。</p>
    </div>
    <label className="pmss-footnote">
      <input type="checkbox" checked={confirmation}
        onChange={event => {setConfirmation(event.target.checked);setReview(null);onReviewed?.(null);setFile("");}}
        aria-label="我已人工确认该出清结果对应本次已提交的报价"/>
      {" "}我已在老师平台人工确认提交该次报价，并确认将导入的结果与本次方案人工关联。
      我理解 PowerBid 无法独立验证老师平台是否真的使用了这份推荐报价。
    </label>
    <div className="pmss-toolbar">
      <p>{file ? "已人工关联文件：" + file : "尚未导入该次出清结果。"}</p>
      <label className="pmss-import-button" style={{cursor: confirmation && !busy ? "pointer" : "not-allowed"}}>
        <UploadCloud size={16}/>{busy ? "正在审核..." : "导入出清结果"}
        <input type="file" accept=".json,application/json" disabled={!confirmation || busy}
          onChange={event => void loadResult(event)}
          aria-label="导入老师平台脱敏出清 JSON" hidden/>
      </label>
    </div>
    {error && <div className="pmss-error" role="alert">{error}</div>}
    {review && <>
      <div className="pmss-error" role="status">只验证了格式、日期、机组身份和24小时数值；
        <strong>“来自本次报价”仅是你的人工声明，尚未经老师平台签名或独立核实。</strong>
        下列数据不能认定为已经证实的新策略收益。</div>
      <div className="pmss-summary">
        <article className="pmss-metric"><span>老师结果中记录的中标量</span>
          <strong>{numeric(review.observed_accepted_mwh, 2)} MWh</strong><small>24小时已观测汇总</small></article>
        <article className="pmss-metric"><span>PowerBid 本地模拟中标量</span>
          <strong>{numeric(review.local_surrogate_accepted_mwh, 2)} MWh</strong><small>原场景/原同行报价的模型预测</small></article>
        <article className="pmss-metric"><span>逐小时中标量误差</span>
          <strong>{numeric(review.hourly_dispatch_mae_mw, 2)} MW</strong><small>仅模型与人工关联结果的描述性比较</small></article>
        <article className="pmss-metric"><span>老师结果的 income 字段合计</span>
          <strong>{review.reported_income_sum == null ? "未完整提供" : numeric(review.reported_income_sum, 2)}</strong>
          <small>{review.income_coverage}/24 小时有记录；不是已审核的净利润</small></article>
      </div>
      <div className="pmss-table-scroll">
        <table className="pmss-table">
          <thead><tr><th>时段</th><th>老师记录中标MW</th><th>本地模拟MW</th><th>老师记录价格</th><th>老师 income</th></tr></thead>
          <tbody>{review.hours.map(hour => <tr key={hour.period}>
            <td>{hour.period}</td>
            <td>{numeric(hour.observed_accepted_mw, 2)}</td>
            <td>{numeric(hour.local_surrogate_accepted_mw, 2)}</td>
            <td>{hour.observed_unit_price == null ? "—" : numeric(hour.observed_unit_price, 2)}</td>
            <td>{hour.reported_income == null ? "—" : numeric(hour.reported_income, 2)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="pmss-footnote">24小时实际出力与老师 income 仅是人工关联的观察值；课程结算口径、成本、
        净收益及本次推荐报价的真实因果关系尚未被独立验证。
        <Download size={14}/> 此次网页暂不生成正式提交文件或自动结算报表。</p>
    </>}
  </div>;
}
