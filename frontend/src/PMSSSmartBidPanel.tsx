import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Download, LockKeyhole, ShieldAlert, Sparkles } from "lucide-react";
import type { PMSSInspection, PMSSNetworkRank, PMSSOptimization, PMSSStrategyTrio, PMSSStrategyGuard } from "./types";
import { numeric } from "./types";
import {
  proposalAuditDocument, type PMSSBidProposal,
} from "./pmssBiddingFlow";
import { buildSmartBidProfiles, buildSmartTrioProfiles, suggestedGuardedProfile, type SmartProfileId } from "./pmssSmartBid";
import "./pmss-smart-bid.css";

type Props = {
  inspection: PMSSInspection;
  target: string;
  analysis: PMSSOptimization | null;
  rankResult: PMSSNetworkRank | null;
  trioResult: PMSSStrategyTrio | null;
  guardResult: PMSSStrategyGuard | null;
  proposal: PMSSBidProposal | null;
  manualReviewReady: boolean;
  pending: boolean;
  onImport: () => void;
  onGenerate: () => void;
  onChoose: (proposal: PMSSBidProposal) => void;
};

const errorMW = (value: number | null) =>
  typeof value === "number" && Number.isFinite(value) ? numeric(value, 2) + " MW" : "缺失";

const historicalFailure = (reason: string) => {
  if (reason.includes("Unit dispatch MAE")) return "留出日期机组出力误差超过研究设定阈值";
  if (reason.includes("Nodal price MAE")) return "留出日期节点电价误差超过研究设定阈值";
  if (reason.includes("coverage")) return "历史出清数据覆盖不足";
  if (reason.includes("topology")) return "历史日期之间电网参数不一致";
  if (reason.includes("Insufficient independent days")) return "独立历史日期不足";
  return reason;
};

const slots = [
  {id: "revenue", title: "收益优先", number: "01"},
  {id: "balanced", title: "均衡策略", number: "02"},
  {id: "defensive", title: "稳健策略", number: "03"},
] as const;

function downloadCandidate(proposal: PMSSBidProposal) {
  const blob = new Blob([JSON.stringify(proposalAuditDocument(proposal), null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "powerbid_candidate_REVIEW_ONLY.json";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function PMSSSmartBidPanel({
  inspection, target, analysis, rankResult, trioResult, guardResult, proposal, manualReviewReady,
  pending, onImport, onGenerate, onChoose,
}: Props) {
  const [selectedId, setSelectedId] = useState<SmartProfileId | "surrogate" | null>(null);
  const [reviewChecked, setReviewChecked] = useState(false);
  const [localError, setLocalError] = useState("");

  // Changing a case, unit, engine result or curve invalidates manual acknowledgement.
  useEffect(() => {
    setSelectedId(null);
    setReviewChecked(false);
    setLocalError("");
  }, [inspection.case_date, target, rankResult, trioResult, guardResult, analysis]);

  const profiles = trioResult
    ? buildSmartTrioProfiles(inspection, trioResult.target_unit_id === target ? trioResult : null, guardResult)
    : buildSmartBidProfiles(inspection, rankResult?.target_unit_id === target ? rankResult : null);
  const suggestion = trioResult ? suggestedGuardedProfile(profiles) : null;
  const hasLoad = inspection.load_mw.length === 24 &&
    inspection.load_mw.every(value => Number.isFinite(value) && value >= 0);
  const targetUnit = inspection.units.find(unit => unit.unit_id === target);
  const validSurrogate = analysis?.target_unit_id === target &&
    !rankResult && analysis.recommended.segments.some(segment => segment.price > 0);
  const fallback = validSurrogate ? analysis : null;
  const chosen = proposal?.caseDate === inspection.case_date &&
    proposal.targetUnitId === target ? proposal : null;
  const selectedProfile = profiles.find(item => item.id === selectedId) ??
    (!selectedId ? suggestion : null);
  // Research-only output is visible, but cannot advance to handoff without B approval.
  const willChoose = selectedProfile?.researchAdmitted === true &&
    guardResult?.status === "HISTORICAL_ONLY_LOCAL_STRATEGY_RESEARCH"
    ? selectedProfile.proposal : null;

  function confirmReview() {
    if (!reviewChecked || !willChoose) return;
    try {
      setLocalError("");
      onChoose(willChoose);
      setReviewChecked(false);
    } catch (cause) {
      setLocalError(cause instanceof Error ? cause.message : "报价审核失败");
    }
  }

  const steps = [
    {label: "选择场景", complete: true},
    {label: "生成候选", complete: profiles.length > 0 || !!fallback},
    {label: "对比推荐", complete: profiles.length > 0 || !!fallback},
    {label: "人工审核", complete: !!chosen},
    {label: "出清复盘", complete: manualReviewReady},
  ];
  const confidence = guardResult?.model_confidence_grade || "尚未取得独立跨日期验证结论";

  return <section className="pmss-smart" aria-label="一键智能报价工作台">
    <div className="pmss-smart-top">
      <div>
        <div className="pmss-smart-kicker"><Sparkles size={15}/> POWERBID · SMART BIDDING</div>
        <h3>智能报价，从选择到复盘。</h3>
        <p>现有算法负责计算，这里负责串联策略、比较结果与人工审核。不会代替老师平台报价或出清。</p>
      </div>
      <span className="pmss-smart-readonly"><LockKeyhole size={14}/> 只读研究 · 不自动提交</span>
    </div>
    <ol className="pmss-smart-steps" aria-label="报价进度">
      {steps.map((step, index) => <li key={step.label} className={step.complete ? "done" : ""}>
        <span>{step.complete ? <CheckCircle2 size={15}/> : String(index + 1).padStart(2, "0")}</span>
        {step.label}
      </li>)}
    </ol>
    <div className="pmss-smart-context">
      <div><small>当前工程与日期</small><strong>{inspection.case_date || "日期缺失"}</strong>
        <span>{inspection.historical_only ? "PMSS 历史研究案例" : "非历史研究快照"}</span></div>
      <div><small>目标机组</small><strong>{targetUnit?.name || "尚未选取"}</strong>
        <span>{target || "请在下方选择目标机组"}</span></div>
      <div><small>输入数据与网络</small><strong>{hasLoad ? "24 小时负荷已读取" : "负荷待补齐"}</strong>
        <span>{inspection.dc_grid_available ? "已加载 DC 网络（不是 PMSS 出清引擎）" : "缺少独立网络参数"}</span></div>
      <button type="button" className="pmss-smart-change" disabled={pending} onClick={onImport}>
        更换案例 <ArrowRight size={15}/>
      </button>
    </div>
    <div className="pmss-smart-action">
      <div><strong>一键生成 · 三类报价策略</strong>
        <p>网络参数齐全时复用现有候选排序；否则仅运行单区域近似，不伪造三种策略或网络校验。</p></div>
      <button type="button" className="pmss-run-button" disabled={pending || !targetUnit || !hasLoad}
        onClick={() => {setSelectedId(null);setReviewChecked(false);onGenerate();}}>
        <Sparkles size={16}/>{pending ? "正在计算，请稍候…" : "生成并比较策略"} <ArrowRight size={16}/>
      </button>
    </div>
    {!hasLoad && <p className="pmss-smart-warning" role="status">负荷数据未包含完整 24 小时，无法开始策略计算。</p>}
    <div className="pmss-smart-title">
      <div><small>STRATEGY COMPARISON</small><h4>三类方案 · 一眼比较</h4></div>
      <span>{profiles.length} / 3 个互不重复且通过基本报价规则检查的候选</span>
    </div>
    <div className="pmss-smart-grid">
      {slots.map(slot => {
        const profile = profiles.find(item => item.id === slot.id);
        const active = !!profile && (selectedId === slot.id || (!selectedId && suggestion?.id === slot.id));
        return <button type="button" key={slot.id}
          className={"pmss-smart-option" + (active ? " active" : "")}
          disabled={!profile || pending}
          onClick={() => {setSelectedId(slot.id);setReviewChecked(false);}}>
          <div className="pmss-smart-option-head"><span>{slot.number} / STRATEGY</span>
            {active && <span className="pmss-smart-picked">当前比较</span>}</div>
          <h5>{slot.title}</h5>
          {profile ? <>
            <p>{profile.subtitle} · {profile.candidate.name}</p>
            <span className="pmss-smart-risk">{
              profile.researchAdmitted ? "通过历史研究筛选（非实盘许可）" : "尚未通过独立风控，禁止作为可信推荐"
            }</span>
            <div className="pmss-smart-values">
              <div><small>本地 DC 模拟边际收益（非实收）</small><strong>{numeric(profile.candidate.expected_margin, 2)}</strong></div>
              <div><small>本地 DC 下行情景（非实收）</small><strong>{numeric(profile.candidate.downside_margin, 2)}</strong></div>
            </div>
            <div className="pmss-smart-bottom">本地模型相对评分 {numeric(profile.candidate.score, 2)}
              <ArrowRight size={16}/></div>
          </> : <>
            <p>当前没有足够的独立、合规候选填入这一类别。</p>
            <div className="pmss-smart-unavailable">暂无真实引擎结果 · 不构造虚拟报价</div>
          </>}
        </button>;
      })}
    </div>
    {!rankResult && fallback && <div className="pmss-smart-fallback">
      <div><strong>仅找到单区域近似候选</strong>
        <p>模拟利润 {numeric(fallback.recommended.total_profit,2)}，不是电网约束验证结果，更不是老师平台出清收益。</p></div>
      <button type="button" disabled={pending} onClick={() => {setSelectedId("surrogate");setReviewChecked(false);}}>
        查看并人工核对
      </button>
    </div>}
    {(trioResult || rankResult) && profiles.length < 3 && <p className="pmss-smart-warning" role="status">
      策略引擎没有返回三条不同且通过基本规则检查的曲线，因此保留空位；未用同一报价冒充不同方案。
    </p>}
    {(trioResult || rankResult) && profiles.length === 0 && <p className="pmss-smart-warning" role="alert">
      当前排序未产生可审核候选，可能存在极端报价或规则不符。请检查网络和市场参数，不能强行推荐。
    </p>}
    {guardResult && <section className="pmss-smart-evidence" aria-label="历史原报价误差与风控依据">
      <div className="pmss-smart-evidence-head">
        <div><span className="pmss-smart-kicker">HISTORICAL MODEL EVIDENCE</span>
          <h4>为什么暂时不能推荐？</h4>
          <p>下表只比较老师平台<strong>历史原报价</strong>的真实出清与本地 DC 复算，
            不代表这三条新方案已在老师平台重新出清。</p>
        </div>
        <span className="pmss-smart-evidence-grade">{guardResult.model_confidence_grade.split("_")[0]} · 历史拟合可信度</span>
      </div>
      <div className="pmss-smart-evidence-grid">
        {guardResult.target_unit_original_bid_historical_fit.map(row => {
          const fleet = guardResult.per_day_original_bid_simulation_vs_real_pmss
            .find(item => item.case_date === row.case_date);
          const holdout = guardResult.untouched_holdout_case_dates.includes(row.case_date);
          const priceRule = guardResult.historical_original_bid_vs_imported_price_rules
            .find(item => item.case_date === row.case_date);
          return <div className={"pmss-smart-evidence-day" + (holdout ? " is-holdout" : "")}
            key={row.case_date}>
            <div className="pmss-smart-evidence-date">
              <strong>{row.case_date}</strong><span>{holdout ? "留出检验" : "训练参考"}</span>
            </div>
            <div><small>G31 原报价出力 MAE</small><strong>{errorMW(row.dispatch_mae_mw)}</strong></div>
            <div><small>10台机组总体出力 MAE</small><strong>{errorMW(fleet?.dispatch_mae_mw ?? null)}</strong></div>
            <div><small>节点电价 MAE</small><strong>{fleet?.nodal_price_mae_pmss_reported_unit_unverified == null
              ? "缺失" : numeric(fleet.nodal_price_mae_pmss_reported_unit_unverified, 2)}</strong></div>
            <div><small>历史报价超出现规则的段数</small>
              <strong>{priceRule ? priceRule.above_ceiling_segment_count +
                priceRule.below_floor_segment_count : "未检查"}</strong></div>
          </div>;
        })}
      </div>
      <small className="pmss-smart-evidence-footnote">MAE 为平均绝对误差；节点电价沿用 PMSS 历史数据数值，
        单位尚未经独立核实。以上均为历史原报价模型拟合，而非新报价预测准确率。</small>
      <div className="pmss-smart-evidence-reasons">
        <strong>{guardResult.historical_original_bid_validation.status === "NOT_VALIDATED"
          ? "历史模型未通过拟合检验" : "历史原报价拟合已达到研究阈值，但不代表新报价有效"}</strong>
        {guardResult.historical_original_bid_validation.reasons.length > 0 && <ul>
          {guardResult.historical_original_bid_validation.reasons.map(reason =>
            <li key={reason}>{historicalFailure(reason)}</li>)}
        </ul>}
        {!guardResult.historical_price_rules_consistent && <p>
          历史原报价存在超出当前导入市场价格上下限的分段，
          可能是市场规则版本或数据口径不一致。没有修改历史记录，
          也不能仅凭当前规则将这些历史报价直接认定为违规。
          在来源核实前禁止据此提高策略可信度。
        </p>}
        {guardResult.original_bid_distinct_training_curves < 2 && <p>训练案例的历史原报价曲线缺少足够变化，无法可靠检验报价变化对结果的影响。</p>}
        {guardResult.holdout_reuses_training_original_bid_curve && <p>留出日期重复使用了训练历史报价，独立性受到限制。</p>}
        <p>未核实的启停、爬坡、备用等约束仍不能假设已经满足；真实 PMSS 新报价出清验证尚未进行。</p>
      </div>
    </section>}
    <div className="pmss-smart-decision">
      <div className="pmss-smart-decision-main">
        <div className="pmss-smart-kicker"><ShieldAlert size={15}/> DECISION & RISK GATE</div>
        <h4>{selectedProfile ? "研究参考：" + selectedProfile.title :
          selectedId === "surrogate" && fallback ? "单区域近似 · 仅供研究" :
          profiles.length > 0 && !suggestion ? "已生成候选 · 暂未通过跨日期风控" : "等待生成候选策略"}</h4>
        <p>{selectedProfile ? selectedProfile.rationale :
          selectedId === "surrogate" ? "当前不具备独立网络复核与多策略比较结果。" :
          "选择历史案例与目标机组后，点击生成。模型结果需人工核验，不能直接当作真实收益证明。"}</p>
        <span className="pmss-smart-risk"><ShieldAlert size={14}/>
          风控状态：尚未获得跨日期、真实 PMSS 新报价出清的独立验证；不具备自动提交准入
        </span>
        <small>风控可信度：{confidence} · 独立日期：{guardResult?.training_case_dates.join("、") || "未验证"} · 留出日期：{guardResult?.untouched_holdout_case_dates.join("、") || "未验证"}</small>
        {selectedProfile && !selectedProfile.researchAdmitted && <p className="pmss-smart-warning" role="status">
          此方案尚未通过跨日期研究准入，不提供可信推荐或人工交接。
          {selectedProfile.riskBlockers?.length
            ? " 风险原因：" + selectedProfile.riskBlockers.join("、") : ""}
        </p>}
      </div>
      <div className="pmss-smart-review">
        <label><input type="checkbox" checked={reviewChecked} disabled={!willChoose || pending}
          onChange={event => setReviewChecked(event.target.checked)}/>
          我已核对日期与报价规则；只有通过独立日期研究准入的候选才能进入人工审核，这仍不代表老师平台批准。
        </label>
        <button type="button" disabled={!reviewChecked || !willChoose || pending}
          onClick={confirmReview}>人工确认候选 <ArrowRight size={16}/></button>
        <small>未通过风控的候选只允许查看研究指标，不能进入推荐审核或模拟真实收益。所有操作均不写入老师平台。</small>
      </div>
    </div>
    {localError && <p role="alert" className="pmss-smart-warning">{localError}</p>}
    {chosen && <div className="pmss-smart-approved">
      <div><CheckCircle2 size={19}/><div><strong>已加入人工审核清单：{chosen.strategyLabel}</strong>
        <p>下方可导出审核 JSON / 24 时段检查表，再由操作者在老师平台手动提交和导入同日出清结果。</p></div></div>
      <button type="button" onClick={() => downloadCandidate(chosen)}><Download size={16}/> 导出审核 JSON</button>
      <div className="pmss-table-scroll"><table className="pmss-table">
        <thead><tr><th>段号</th><th>起始 MW</th><th>结束 MW</th><th>报价</th></tr></thead>
        <tbody>{chosen.segments.map((seg,i) => <tr key={i}>
          <td>{i+1}</td><td>{numeric(seg.start_power,2)}</td>
          <td>{numeric(seg.end_power,2)}</td><td>{numeric(seg.price,2)}</td>
        </tr>)}</tbody>
      </table></div>
    </div>}
    {manualReviewReady && <p className="pmss-smart-warning" role="status">
      已完成一次操作者人工关联的结果复盘。模型误差可描述，但仍不构成新报价真实收益的因果证明。
    </p>}
  </section>;
}
