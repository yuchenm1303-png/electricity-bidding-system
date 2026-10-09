import { useState } from "react";
import { Activity, ArrowRight, Download, ShieldCheck } from "lucide-react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { analyzePMSSCandidateDispatch } from "./api";
import { PMSSJointMwhPanel } from "./PMSSJointMwhPanel";
import {
  numeric, type PMSSCandidateDispatchRange, type PMSSInspection,
  type PMSSNetworkRank, type PMSSOptimization,
} from "./types";

type CurveSegment = {start_power: number; end_power: number; price: number};
type Selection = "ranked" | "five-segment";

function downloadRiskSummary(report: PMSSCandidateDispatchRange, label: string) {
  // The reviewed JSON contains only research diagnostics and curve identity,
  // never raw PMSS bids, observed dispatch, credentials or settlement amounts.
  const payload = {
    ...report,
    source: label,
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"}),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "powerbid_candidate_dispatch_uncertainty_RESEARCH_ONLY.json";
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function PMSSCandidateDispatchPanel({
  snapshot, inspection, target, analysis, rankResult, otherBusy,
}: {
  snapshot: Record<string, unknown>;
  inspection: PMSSInspection;
  target: string;
  analysis: PMSSOptimization | null;
  rankResult: PMSSNetworkRank | null;
  otherBusy: boolean;
}) {
  const [choice, setChoice] = useState<Selection>("ranked");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [last, setLast] = useState<{
    key: string; report: PMSSCandidateDispatchRange; label: string;
  } | null>(null);

  const networkCurve: CurveSegment[] | null = rankResult
    ? rankResult.best_candidate.price_blocks.map(([start_power, end_power, price]) => ({
      start_power, end_power, price,
    })) : null;
  const fiveCurve = analysis?.recommended.segments ?? null;
  // Fallback if only one type of proposal is available. Both must have
  // passed the server-side new-bid legality gate before a result is returned.
  const effectiveChoice: Selection =
    choice === "ranked" && !networkCurve && fiveCurve ? "five-segment" :
    choice === "five-segment" && !fiveCurve && networkCurve ? "ranked" : choice;
  const plan = effectiveChoice === "ranked"
    ? networkCurve ?? fiveCurve
    : fiveCurve ?? networkCurve;
  const label = effectiveChoice === "ranked" && networkCurve
    ? "网络优先风险排序的本地候选"
    : "五段搜索的本地候选";
  const key = JSON.stringify({target, curve: plan, caseDate: inspection.case_date});
  const displayed = last?.key === key ? last.report : null;

  async function run() {
    if (!plan || !target || busy || otherBusy || !inspection.dc_grid_available) return;
    setBusy(true);
    setError("");
    setLast(null);
    try {
      const report = await analyzePMSSCandidateDispatch(snapshot, target, plan);
      if (report.target_unit_id !== target || report.hours.length !== 24) {
        throw new Error("分析接口返回的机组或时段不一致");
      }
      if (report.safe_for_live_submission || report.counterfactual_pmss_verified ||
          report.uses_historical_outcomes_as_forecast || report.pmss_write_performed ||
          report.pmss_clearing_executed) {
        throw new Error("研究模式状态异常：禁止把模拟结果显示成真实出清");
      }
      setLast({key, report, label});
    } catch (err) {
      setError(err instanceof Error ? err.message : "中标量区间分析失败");
    } finally {
      setBusy(false);
    }
  }

  return <section className="pmss-panel" aria-label="候选报价中标量不确定性">
    <div className="pmss-panel-head">
      <div>
        <small>05 / OPTIMAL DISPATCH UNCERTAINTY</small>
        <h3>新报价 · 中标量上下界</h3>
        <p>不是只取一次线性规划结果，而是逐小时寻找相同最低申报成本下，
          目标机组可能的最小与最大中标MW。</p>
      </div>
      <span className="pmss-state-label"><ShieldCheck size={14}/> 仅离线研究</span>
    </div>

    <div className="pmss-toolbar">
      <label className="pmss-rank-control">
        选择已生成的候选曲线
        <select aria-label="选择候选报价方案" value={effectiveChoice}
          onChange={event => {setChoice(event.target.value as Selection);setError("");}}
          disabled={busy || otherBusy}>
          <option value="ranked" disabled={!networkCurve}>网络优先风险排序最高候选</option>
          <option value="five-segment" disabled={!fiveCurve}>五段报价搜索候选</option>
        </select>
      </label>
      <button className="pmss-run-button" type="button"
        disabled={!inspection.dc_grid_available || !plan || busy || otherBusy || !target}
        onClick={() => void run()}>
        {busy ? "正在验证24小时出力范围…" : "计算候选中标区间"}
        <ArrowRight size={16}/>
      </button>
    </div>

    {!inspection.dc_grid_available && <p className="pmss-footnote">
      需要已核实的节点拓扑、机组接线和逐节点负荷；不会把单区域结果冒充网络出清。
    </p>}
    {!plan && <p className="pmss-footnote">
      请先运行上方网络优先报价排序，或先完成五段报价搜索，再分析其不确定性。
    </p>}
    {error && <div className="pmss-error" role="alert">{error}</div>}

    {displayed && <>
      <div className="pmss-summary" role="group" aria-label="24小时中标量范围">
        <article className="pmss-metric"><span>逐小时下界累计</span>
          <strong>{numeric(displayed.minimum_accepted_mwh, 1)} MWh</strong>
          <small>不是SCUC联合可行最小发电量</small></article>
        <article className="pmss-metric"><span>普通DC-LP解累计</span>
          <strong>{numeric(displayed.default_lp_accepted_mwh, 1)} MWh</strong>
          <small>仅是其中一组等成本最优分配</small></article>
        <article className="pmss-metric"><span>逐小时上界累计</span>
          <strong>{numeric(displayed.maximum_accepted_mwh, 1)} MWh</strong>
          <small>不是实际PMSS中标承诺</small></article>
        <article className="pmss-metric"><span>存在明显歧义的时段</span>
          <strong>{displayed.ambiguous_hours} / 24</strong>
          <small>大于1MW区间宽度</small></article>
      </div>
      <div className="pmss-chart" role="img" aria-label="24小时最小、普通解和最大中标MW曲线">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={displayed.hours} margin={{top:14,right:16,bottom:5,left:-8}}>
            <CartesianGrid stroke="var(--ta-border)" strokeDasharray="4 5" vertical={false}/>
            <XAxis dataKey="period" tick={{fill:"var(--ta-muted)",fontSize:11}}
              tickLine={false} axisLine={false}/>
            <YAxis tick={{fill:"var(--ta-muted)",fontSize:11}}
              tickLine={false} axisLine={false} width={64}/>
            <Tooltip contentStyle={{
              background:"var(--ta-panel)",color:"var(--ta-ink)",
              border:"1px solid var(--ta-border)",borderRadius:11,
            }}/>
            <Legend verticalAlign="top" height={32}/>
            <Line dataKey="minimum_accepted_mw" name="最小可中标MW" type="linear"
              stroke="#039855" dot={false} strokeWidth={2} isAnimationActive={false}/>
            <Line dataKey="default_lp_accepted_mw" name="普通LP解MW" type="linear"
              stroke="#465fff" dot={false} strokeWidth={2} isAnimationActive={false}/>
            <Line dataKey="maximum_accepted_mw" name="最大可中标MW" type="linear"
              stroke="#e4a15b" dot={false} strokeWidth={2} isAnimationActive={false}/>
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="pmss-table-scroll"><table className="pmss-table">
        <thead><tr><th>时段</th><th>最小MW</th><th>普通解MW</th>
          <th>最大MW</th><th>差异MW</th></tr></thead>
        <tbody>{displayed.hours.map(hour => <tr key={hour.period}>
          <td>{hour.period}</td>
          <td>{numeric(hour.minimum_accepted_mw, 2)}</td>
          <td>{numeric(hour.default_lp_accepted_mw, 2)}</td>
          <td>{numeric(hour.maximum_accepted_mw, 2)}</td>
          <td>{numeric(hour.range_width_mw, 2)}</td>
        </tr>)}</tbody>
      </table></div>
      {displayed.ambiguous_hours > 0 && <div className="pmss-error" role="status">
        <strong>中标分配不唯一。</strong> 当前候选在{displayed.ambiguous_hours}个小时存在
        超过1MW的同成本解差异；单条普通LP出力轨迹不应被当作确定预测。
      </div>}
      {displayed.original_peer_units_over_current_price_rule > 0 &&
        <div className="pmss-error" role="status">
          历史其他机组中有{displayed.original_peer_units_over_current_price_rule}台
          已保存报价超出快照记录的当前市场价格规则。
          不能把这种历史竞争环境当作现在可直接使用的市场预测。
        </div>}
      <div className="pmss-toolbar">
        <p>报告仅包含研究统计、没有PMSS真实新报价出清或收益数据。</p>
        <button className="pmss-run-button" type="button"
          onClick={() => downloadRiskSummary(displayed, label)}>
          <Download size={15}/> 下载区间审核JSON
        </button>
      </div>
    </>}
    {plan && inspection.dc_grid_available && <PMSSJointMwhPanel
      key={key}
      snapshot={snapshot}
      target={target}
      candidate={plan}
      planLabel={label}
      disabled={busy || otherBusy}
    />}
    <p className="pmss-footnote"><Activity size={14}/>
      模型边界：逐小时无损DC网络、同行历史报价固定，未纳入启停、
      爬坡、备用、AC损耗与老师PMSS特有的结算规则。
      {inspection.joint_readiness.ready
        ? " 虽然本快照具备独立联合机组参数准入，当前区间仍不属于联合MILP结果。"
        : " 机组技术参数尚未独立核实，不能声称这个区间满足24小时机组联合运行约束。"}
      禁止用历史1001价假设为新报价结算。
    </p>
  </section>;
}
