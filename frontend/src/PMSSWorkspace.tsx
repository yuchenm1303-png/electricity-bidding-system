import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { Activity, ArrowRight, Database, Download, FileJson2, ShieldCheck, UploadCloud } from "lucide-react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { evaluatePMSSNetwork, inspectPMSS, optimizePMSS, rankPMSSNetwork } from "./api";
import { numeric, type PMSSInspection, type PMSSNetworkComparison, type PMSSNetworkRank, type PMSSOptimization } from "./types";
import "./pmss-studio.css";
import { MarketExplorer, OptimizationHourReview } from "./PMSSInsights";
import { PMSSCandidateDispatchPanel } from "./PMSSCandidateDispatchPanel";
import { PMSSHoldoutGatePanel } from "./PMSSHoldoutGatePanel";

const tooltipStyle = {
  background: "var(--ta-panel)", color: "var(--ta-ink)",
  border: "1px solid var(--ta-border)", borderRadius: 11, fontSize: 12,
};
const axisStyle = { fill: "var(--ta-muted)", fontSize: 11 };

function Metric({label, value, detail}: {label: string; value: string; detail: string}) {
  return <article className="pmss-metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

function saveReview(result: PMSSOptimization) {
  const data = {
    source: "LOCAL SURROGATE ONLY - NOT PMSS CLEARED OR SUBMITTED",
    targetUnitId: result.target_unit_id, marketType: "DA",
    startPeriod: 1, endPeriod: 24,
    segments: result.recommended.segments.map((s, index) => ({
      segmentOrder: index + 1, startPower: s.start_power,
      endPower: s.end_power, price: s.price,
    })),
  };
  const objectUrl = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], {type: "application/json"})
  );
  const link = window.document.createElement("a");
  link.href = objectUrl;
  link.download = "powerbid_pmss_local_review.json";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

function saveTechnicalTemplate(inspection: PMSSInspection) {
  // Deliberately leave every unknown physical parameter null.
  // The offline joint MILP refuses these placeholders until independently supplied.
  const data = Object.fromEntries(inspection.units.map(unit => [
    unit.unit_id,
    Object.fromEntries(inspection.joint_required_technical_fields.map(field => [
      field, field === "unit_id" ? unit.unit_id : null,
    ])),
  ]));
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], {type:"application/json"})
  );
  const link = window.document.createElement("a");
  link.href = url;
  link.download = "powerbid_24h_unit_technical_BLANK_TEMPLATE.json";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function PMSSWorkspace() {
  const picker = useRef<HTMLInputElement | null>(null);
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);
  const [inspection, setInspection] = useState<PMSSInspection | null>(null);
  const [analysis, setAnalysis] = useState<PMSSOptimization | null>(null);
  const [networkResult, setNetworkResult] = useState<PMSSNetworkComparison | null>(null);
  const [networkBusy, setNetworkBusy] = useState(false);
  const [rankBusy, setRankBusy] = useState(false);
  const [rankResult, setRankResult] = useState<PMSSNetworkRank | null>(null);
  const [riskAversion, setRiskAversion] = useState(0.5);
  const [target, setTarget] = useState("");
  const [minimum, setMinimum] = useState(0);
  const [maximum, setMaximum] = useState(1000);
  const [step, setStep] = useState(200);
  const [iterations, setIterations] = useState(2);
  const [busy, setBusy] = useState(false);
  const [activeTask, setActiveTask] = useState<"import"|"optimize"|null>(null);
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState("");

  const importFile = async (file: File) => {
    if (busy || networkBusy || rankBusy) return;
    setInspection(null); setSnapshot(null); setAnalysis(null);
    setNetworkResult(null); setRankResult(null); setFileName(""); setError("");
    if (file.size > 700_000) {
      setError("文件超过 700 KB，使用只读导出器生成的精简脱敏 JSON。");
      return;
    }
    setBusy(true); setActiveTask("import");
    try {
      const data: unknown = JSON.parse(await file.text());
      if (!data || typeof data !== "object" || Array.isArray(data)) {
        throw new Error("PMSS 快照必须是 JSON 对象");
      }
      const raw = data as Record<string, unknown>;
      const inspected = await inspectPMSS(raw);
      setSnapshot(raw);
      setInspection(inspected);
      setMinimum(inspected.historical_bid_rule_audit.price_floor ?? 0);
      setMaximum(Math.min(10000, inspected.historical_bid_rule_audit.price_ceiling ?? 1000));
      setFileName(file.name);
      setTarget(inspected.units[0]?.unit_id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法读取快照");
    } finally {
      setBusy(false); setActiveTask(null);
    }
  };
  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void importFile(file);
  };
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const file = event.dataTransfer.files[0];
    if (file) void importFile(file);
  };

  const run = async () => {
    if (!snapshot || !target || busy || networkBusy) return;
    if (![minimum, maximum, step].every(Number.isFinite) ||
        minimum < (inspection?.historical_bid_rule_audit.price_floor ?? 0) ||
        maximum > (inspection?.historical_bid_rule_audit.price_ceiling ?? 10000) ||
        maximum > 10000 || maximum < minimum || step <= 0) {
      setError("候选报价必须符合当前 PMSS 市场价格上下限，且步长大于零");
      return;
    }
    const count = Math.floor((maximum - minimum) / step) + 1;
    if (count < 1 || count > 21) {
      setError("最多允许 21 个候选价格，请增大步长");
      return;
    }
    const prices = Array.from({length: count}, (_, i) => Number((minimum + step * i).toFixed(6)));
    if (Math.abs(prices[prices.length - 1] - maximum) > 1e-6) {
      if (prices.length >= 21) {setError("价格候选过多，请增加步长");return;}
      prices.push(maximum);
    }
    setAnalysis(null);
    setNetworkResult(null);
    setError("");
    setBusy(true); setActiveTask("optimize");
    try {
      setAnalysis(await optimizePMSS(snapshot, target, prices, iterations));
    } catch (err) {
      setError(err instanceof Error ? err.message : "本地优化失败");
    } finally {
      setBusy(false); setActiveTask(null);
    }
  };

  const runNetwork = async () => {
    if (!snapshot || !analysis || !target || !inspection?.dc_grid_available ||
        busy || networkBusy) return;
    setNetworkBusy(true);
    setNetworkResult(null);
    setError("");
    try {
      const report = await evaluatePMSSNetwork(
        snapshot, target, analysis.recommended.segments,
      );
      setNetworkResult(report);
    } catch (err) {
      setError(err instanceof Error ? err.message : "DC 网络约束试算失败");
    } finally {
      setNetworkBusy(false);
    }
  };

  const runRank = async () => {
    if (!snapshot || !target || !inspection?.dc_grid_available ||
        busy || networkBusy || rankBusy) return;
    setRankBusy(true);
    setRankResult(null);
    setError("");
    try {
      setRankResult(await rankPMSSNetwork(snapshot, target, riskAversion, 0.05));
    } catch (err) {
      setError(err instanceof Error ? err.message : "网络优先策略排序失败");
    } finally {
      setRankBusy(false);
    }
  };

  const network = inspection?.network;
  const series = network?.hourly.map(item => ({
    period: item.hour, spread: item.lmp_spread,
    shadowed: item.nonzero_shadow_branches,
  })) || [];
  const comparison = analysis?.recommended.hours.map((item, index) => ({
    period: item.period,
    recommended: item.target_accepted_mw,
    actual: analysis.baseline_backtest?.hours[index]?.observed_accepted_mw ?? null,
    original: analysis.baseline_backtest?.hours[index]?.surrogate_accepted_mw ?? null,
  })) || [];

  const dcHours = networkResult?.baseline.hours.map((base, index) => ({
    period: base.period,
    originalDC: base.target_mw,
    proposedDC: networkResult.recommended?.hours[index]?.target_mw ?? null,
    observedPMSS: analysis?.baseline_backtest?.hours[index]?.observed_accepted_mw ?? null,
  })) || [];

  return <section className="pmss-workspace">
    <div className="pmss-hero">
      <div><span className="pmss-eyebrow"><Activity size={15}/> PMSS / READ-ONLY MARKET INTELLIGENCE</span>
        <h2>真实市场数据与报价策略</h2>
        <p>读取脱敏历史快照，分析24时段节点电价、线路约束和机组中标，再生成本地五段报价建议。</p>
        <div className="pmss-hero-tags">
          <span><ShieldCheck size={14}/> 零平台写入</span>
          <span><Database size={14}/> 实际出清结果</span>
          <span>本地策略搜索</span>
        </div>
      </div>
      <button className="pmss-import-button" type="button" disabled={busy || networkBusy} onClick={() => picker.current?.click()}>
        <UploadCloud size={19}/>{activeTask==="import" ? "正在校验..." : inspection ? "更换快照" : "导入快照"}
      </button>
      <input ref={picker} type="file" accept=".json,application/json" hidden
        aria-label="导入 PMSS 脱敏 JSON" onChange={onFile}/>
    </div>
    <div className="pmss-process-steps" aria-label="PMSS 研究工作流程">
      <span className={inspection ? "complete" : "current"}><b>01</b> 导入脱敏快照</span>
      <span className={inspection ? "complete" : ""}><b>02</b> 市场与机组检查</span>
      <span className={analysis ? "complete" : inspection ? "current" : ""}><b>03</b> 本地优化与复核</span>
      {fileName && <span className="pmss-file-label" title={fileName}>{fileName}</span>}
    </div>
    <p className="pmss-privacy"><ShieldCheck size={17}/>快照仅传至本站同源后端进行当前请求的内存计算，不会自动存盘；
      不要上传 Cookie、Token 或账户信息。本页不能向 PMSS 提交报价或启动出清。</p>
    {error && <div className="pmss-error" role="alert">{error}</div>}
    {!inspection && <div className="pmss-empty" onDragOver={event => event.preventDefault()} onDrop={onDrop}>
      <FileJson2 size={42} strokeWidth={1.3}/>
      <h3>尚未导入 PMSS 数据</h3>
      <p>在可信服务器执行只读快照导出，再将不含认证信息的 JSON 拖放至此或手动选择。无需在网页端登录老师平台。</p>
      <button type="button" onClick={() => picker.current?.click()}>选择 JSON 文件 <ArrowRight size={15}/></button>
    </div>}
    {inspection && <>
      <div className="pmss-section-head"><div><small>01 / MARKET SNAPSHOT</small><h3>历史市场场景</h3>
        <p>{inspection.case_date || "未标注日期"} · {inspection.forecast_source}</p>
      </div><span className="pmss-status">字段已验证</span></div>
      <div className="pmss-metrics">
        <Metric label="机组数据" value={String(inspection.units.length) + " 台"} detail="真实容量及分段报价"/>
        <Metric label="日前负荷峰值" value={numeric(Math.max(...inspection.load_mw), 2) + " MW"} detail="历史场景输入，并非未来预测"/>
        <Metric label="节点电价" value={network ? String(network.node_count) + " 个" : "未包含"} detail="24小时历史 LMP"/>
        <Metric label="线路潮流" value={network ? String(network.branch_count) + " 条" : "未包含"} detail="已出清支路数据"/>
      </div>
      <div className="pmss-privacy">
        <ShieldCheck size={17}/>
        <span>当前快照申报价格规则：
          {inspection.historical_bid_rule_audit.price_floor ?? "未提供"} 至
          {inspection.historical_bid_rule_audit.price_ceiling ?? "未提供"}。
          新生成的候选曲线必须遵守此限制；
          现有历史报价将保留原值用于研究，不自动修改。</span>
      </div>
      {inspection.historical_bid_rule_audit.original_segments_outside_current_range > 0 &&
        <div className="pmss-error" role="status">
          历史原始报价与当前读取的市场价格限制不一致：
          {inspection.historical_bid_rule_audit.original_units_outside_current_range} 台机组、
          {inspection.historical_bid_rule_audit.original_segments_outside_current_range} 个历史报价段超出当前限制。
          历史最高申报价为 {numeric(inspection.historical_bid_rule_audit.largest_original_price, 2)}。
          不能仅凭当前规则断定历史提交违规，也不能用历史报价为新报价越界提供依据。
        </div>}
      <div className="pmss-panel">
        <div className="pmss-panel-head">
          <div>
            <small>05 / INTEGRATED 24H MODEL</small>
            <h3>24小时联合机组约束 · 数据准入</h3>
            <p>联合 DC 网络 + 机组启停 + 爬坡 + 最短开停机已有独立 MILP 研究引擎；
              没有逐机组可靠参数时，不允许用猜测值计算。</p>
          </div>
          <span className="pmss-state-label">真实参数未齐全</span>
        </div>
        <div className="pmss-summary">
          <Metric label="需要独立运行参数的机组"
            value={inspection.joint_readiness.total_units + " 台"}
            detail="必须与 PMSS 机组 ID 完全一致"/>
          <Metric label="已完整提供的机组"
            value={inspection.joint_readiness.supplied_units + " 台"}
            detail="当前快照不包含联合模型技术参数"/>
          <Metric label="实际联合 MILP 准入"
            value={inspection.joint_readiness.ready ? "可试算" : "已阻止"}
            detail="禁止推断爬坡、启停与初始状态"/>
        </div>
        {inspection.technical_evidence && <>
          <div className="pmss-result-toolbar">
            <h4>老师平台原始机组字段 · 取值证据</h4>
            <span className="pmss-state-label">含义及单位待核验</span>
          </div>
          <p className="pmss-footnote">
            当前导入的脱敏快照声明：{inspection.technical_evidence.unit_count}台机组
            与原始机组表逐ID匹配，容量字段一致
            {inspection.technical_evidence.capacity_match_count}台；
            以下只是原始字段统计，不证明其单位、课程规则或物理约束含义。
            不会自动用于联合 MILP。
          </p>
          <div className="pmss-table-scroll"><table className="pmss-table">
            <thead><tr><th>原始字段</th><th>覆盖机组</th><th>零值</th>
              <th>取值区间</th><th>待核验含义</th></tr></thead>
            <tbody>{Object.entries(inspection.technical_evidence.observed_fields).map(
              ([field, stat]) => <tr key={field}>
                <td>{field}</td><td>{stat.present}/{inspection.technical_evidence!.unit_count}</td>
                <td>{stat.zero}</td>
                <td>{stat.min === null ? "无数据" :
                  numeric(stat.min,2) + " ～ " + numeric(stat.max ?? stat.min,2)}</td>
                <td>{stat.meaning}</td>
              </tr>,
            )}</tbody>
          </table></div>
          <p className="pmss-footnote">
            注意：10台机组若均出现相同20的爬坡相关字段或0的开停机字段，
            也不能直接把它们解释成 MW/h、0小时或零启停成本。
            参数来源由上传文件声明，公开网页不具备独立核真能力。
          </p>
        </>}
        {!inspection.technical_evidence && <p className="pmss-footnote">
          这份快照尚未加入原始机组技术字段的脱敏取值证据。
          可在可信服务器用带 --include-technical-evidence 的网架合并脚本重新导出；
          真实联合求解仍保持锁定。
        </p>}
        {inspection.scene_constraint_evidence && <>
          <div className="pmss-result-toolbar">
            <h4>场景计算约束 · 原始编码审计</h4>
            <span className="pmss-state-label">只读观察 · 未核实启用含义</span>
          </div>
          <p className="pmss-footnote">
            已上传的脱敏场景摘要包含
            {inspection.scene_constraint_evidence.constraint_rows}条计算约束记录、
            {inspection.scene_constraint_evidence.initial_rows}条初始状态记录。
            以下的编码0和编码1不是已核实的关/开状态，
            也不代表当前案例已被验证具有真实机组启停约束。
          </p>
          <div className="pmss-table-scroll"><table className="pmss-table">
            <thead><tr><th>PMSS 场景字段</th><th>编码1</th><th>编码0</th>
              <th>缺失</th><th>其他/待确认</th></tr></thead>
            <tbody>{Object.entries(inspection.scene_constraint_evidence.switches).map(
              ([field, stat]) => <tr key={field}>
                <td>{field}</td>
                <td>{stat.value_1}</td><td>{stat.value_0}</td>
                <td>{stat.missing}</td><td>{stat.unrecognized}</td>
              </tr>,
            )}</tbody>
          </table></div>
          <div className="pmss-result-toolbar"><h4>初始状态输入 · 取值覆盖</h4>
            <span className="pmss-state-label">时间及状态编码待确认</span></div>
          <div className="pmss-table-scroll"><table className="pmss-table">
            <thead><tr><th>原始字段</th><th>非空行</th><th>数值行</th>
              <th>原始数值范围</th></tr></thead>
            <tbody>{Object.entries(inspection.scene_constraint_evidence.initial_fields).map(
              ([field, stat]) => <tr key={field}>
                <td>{field}</td><td>{stat.present}</td><td>{stat.numeric}</td>
                <td>{stat.minimum === null ? "未提供数值" :
                  numeric(stat.minimum, 2) + " ～ " +
                  numeric(stat.maximum ?? stat.minimum, 2)}</td>
              </tr>,
            )}</tbody>
          </table></div>
          <p className="pmss-footnote">
            这里展示的是上传文件的统计，网页不能独立验证来源。
            初始开停机状态、持续时间、成本和开关实际语义都尚未核实；
            24小时联合 MILP 不会因此自动解锁。
          </p>
        </>}
        {!inspection.scene_constraint_evidence && <p className="pmss-footnote">
          暂无当前场景的只读约束证据。联网读取恢复后，可在可信环境
          生成匿名汇总并合并到脱敏快照，再在此显示开关与初始状态字段统计。
        </p>}
        <div className="pmss-toolbar">
          <p>可生成无默认值的参数模板，再使用课程或可信来源逐台补齐。
            在完成之前，继续使用上方独立 DC 网络报价研究，不冒充联合优化。</p>
          <button className="pmss-run-button" type="button"
            onClick={() => saveTechnicalTemplate(inspection)}>
            <Download size={16}/> 下载空白参数模板
          </button>
        </div>
        <p className="pmss-footnote">
          模板内尚未知晓的字段统一为 null，**不是默认值**；
          需要补齐全部机组初始开停机状态、出力、持续时间、爬坡、启停成本和最短开停机时间。
          目前联合策略研究仅通过合成教学数据测试；真实 PMSS 机组参数尚未验证。
          在受控本地环境中可使用 scripts/study_pmss_joint.py 离线检查及求解，
          不会自动向老师平台提交。
        </p>
      </div>
      <MarketExplorer inspection={inspection}/>
      <div className="pmss-panel">
        <div className="pmss-panel-head">
          <div>
            <small>04 / NETWORK-FIRST BID RESEARCH</small>
            <h3>网络优先 · 五段报价风险排序</h3>
            <p>在真实线路限额和节点负荷约束下，比较多个符合当前价格规则的候选方案。
              每个方案均重新求解24小时 DC 网络；三种竞争者报价情景只是敏感性测试。</p>
          </div>
          <span className="pmss-state-label">离线策略研究</span>
        </div>
        <div className="pmss-toolbar">
          <label className="pmss-rank-control">
            风险厌恶程度
            <select value={riskAversion}
              onChange={e => {setRiskAversion(Number(e.target.value));setRankResult(null);}}>
              <option value={0}>0 · 关注平均模拟利润</option>
              <option value={0.5}>0.5 · 平衡收益与下行</option>
              <option value={1}>1 · 关注下行情景</option>
            </select>
          </label>
          <button className="pmss-run-button" type="button"
            disabled={!inspection.dc_grid_available || busy || networkBusy || rankBusy || !target}
            onClick={() => void runRank()}>
            {rankBusy ? "正在复算多组网络方案..." : "运行网络优先策略排序"}
            <ArrowRight size={16}/>
          </button>
        </div>
        {!inspection.dc_grid_available && <p className="pmss-footnote">
          请先导入由可信服务器核实线路电抗、热额定 MW、39节点负荷的 dcNetwork 快照。
          没有真实拓扑时不会退化成单区域搜索后假称网络优化。
        </p>}
        {rankResult && <>
          <p className="pmss-footnote">
            证据状态：<strong>仅供研究，尚无独立留出日期的验证</strong>。
            此处是最多四个合法候选的模型内排序，并非 PMSS 真实出清、
            全局最优或可实际提交的报价。当前仅使用历史竞争报价，
            对其进行 ±5% 的人为价格扰动。
          </p>
          {rankResult.historical_units_outside_current_rule > 0 &&
            <div className="pmss-error" role="status">
              这份历史快照有 {rankResult.historical_units_outside_current_rule} 台机组
              的已保存报价超出当前价格规则，因此不能直接把历史原报价的模拟得分
              与合法新候选的分数当作公平的改进证据。
            </div>}
          <div className="pmss-summary">
            <Metric label="已评估的合法候选" value={String(rankResult.eligible_candidates.length)}
              detail="原始历史报价不计作新候选"/>
            <Metric label="最高风险加权模型得分" value={numeric(rankResult.best_candidate.score,2)}
              detail="合成情景下的本地利润代理"/>
            <Metric label="最优候选下行利润代理"
              value={numeric(rankResult.best_candidate.downside_margin,2)}
              detail="不是PMSS结算收入"/>
          </div>
          <div className="pmss-table-scroll"><table className="pmss-table">
            <thead><tr><th>候选策略</th><th>风险加权得分</th><th>期望利润代理</th>
              <th>下行利润代理</th><th>模拟中标电量</th></tr></thead>
            <tbody>{rankResult.eligible_candidates.map(item =>
              <tr key={item.name}>
                <td>{item.name}</td>
                <td>{numeric(item.score,2)}</td>
                <td>{numeric(item.expected_margin,2)}</td>
                <td>{numeric(item.downside_margin,2)}</td>
                <td>{numeric(item.expected_accepted_mwh,2)} MWh</td>
              </tr>)}</tbody>
          </table></div>
          <div className="pmss-result-toolbar"><h4>模型得分最高的合法五段曲线</h4>
            <span className="pmss-state-label">不可直接提交</span></div>
          <div className="pmss-table-scroll"><table className="pmss-table">
            <thead><tr><th>段号</th><th>起始出力 MW</th><th>结束出力 MW</th><th>申报价格</th></tr></thead>
            <tbody>{rankResult.best_candidate.price_blocks.map((block,index) =>
              <tr key={index}><td>{index+1}</td><td>{numeric(block[0],2)}</td>
                <td>{numeric(block[1],2)}</td><td>{numeric(block[2],2)}</td></tr>)}</tbody>
          </table></div>
          <p className="pmss-footnote">
            尚未将机组启停、跨时段爬坡、网损和 PMSS 特殊结算价纳入上述排序；
            目前已有独立联合24小时 MILP 研究模块，但不能假称本次排序已使用它。
            不提供真实报价提交或直接导出 PMSS 保存报文。
          </p>
        </>}
      </div>

      {network && <div className="pmss-panel">
        <div className="pmss-panel-head"><div><small>02 / OBSERVED NETWORK</small><h3>节点价格分化与历史线路影子价格</h3>
          <p>这里展示 PMSS 历史出清，不推断新报价对潮流和节点电价的影响。</p></div>
          <span className="pmss-state-label">真实历史结果</span>
        </div>
        <div className="pmss-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series} margin={{top:16,right:17,bottom:2,left:-10}}>
              <CartesianGrid stroke="var(--ta-border)" vertical={false}/>
              <XAxis dataKey="period" tick={axisStyle} axisLine={false} tickLine={false}/>
              <YAxis yAxisId="lmp" tick={axisStyle} axisLine={false} tickLine={false}/>
              <YAxis yAxisId="branch" orientation="right" allowDecimals={false} tick={axisStyle} axisLine={false} tickLine={false}/>
              <Tooltip contentStyle={tooltipStyle}/><Legend verticalAlign="top" height={32}/>
              <Line yAxisId="lmp" isAnimationActive={false} dataKey="spread" name="节点价差" stroke="#465fff" strokeWidth={2.6} dot={false}/>
              <Line yAxisId="branch" isAnimationActive={false} dataKey="shadowed" name="影子价格非零线路数" stroke="#e4a15b" strokeWidth={2.2} dot={false}/>
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="pmss-table-scroll"><table className="pmss-table">
          <thead><tr><th>线路</th><th>非零影子价格时段</th><th>影子价格峰值</th><th>潮流绝对值峰值</th></tr></thead>
          <tbody>{network.most_shadowed.slice(0, 8).map(item => <tr key={item.element_id}>
            <td>{item.name || item.element_id}</td>
            <td>{item.hours_nonzero_shadow} / 24</td>
            <td>{numeric(item.peak_abs_shadow, 2)}</td>
            <td>{item.peak_abs_flow_mw == null ? "—" : numeric(item.peak_abs_flow_mw, 2) + " MW"}</td>
          </tr>)}</tbody>
        </table></div>
        <p className="pmss-footnote">非零影子价格不是线路过载证明。{inspection.dc_grid_available ? "当前已经加载本地 DC 网络拓扑；该历史影子价格仍不能直接用来预测候选报价结果。" : "当前未导入真实网络拓扑和线路容量，无法重算网络出清。"}</p>
      </div>}
      <div className="pmss-panel">
        <div className="pmss-panel-head"><div><small>03 / FIVE-SEGMENT STRATEGY</small><h3>五段价格—电量曲线搜索</h3>
          <p>复用本地单区域统一价引擎；生成的是教学模拟报价，不是 PMSS 重出清。</p></div>
          <span className="pmss-state-label">本地模拟</span>
        </div>
        <div className="pmss-controls">
          <label>目标机组<select disabled={busy || networkBusy} value={target} onChange={e => {setTarget(e.target.value);setAnalysis(null);setNetworkResult(null);setRankResult(null);}}>
            {inspection.units.map(item => <option key={item.unit_id} value={item.unit_id}>{item.name}</option>)}
          </select></label>
          <label>最低报价<input type="number" disabled={busy || networkBusy} min="0" max="10000" value={minimum} onChange={e => {setMinimum(Number(e.target.value));setAnalysis(null);setNetworkResult(null);}}/></label>
          <label>最高报价<input type="number" disabled={busy || networkBusy} min="0" max="10000" value={maximum} onChange={e => {setMaximum(Number(e.target.value));setAnalysis(null);setNetworkResult(null);}}/></label>
          <label>报价步长<input type="number" disabled={busy || networkBusy} min="1" value={step} onChange={e => {setStep(Number(e.target.value));setAnalysis(null);setNetworkResult(null);}}/></label>
          <label>局部迭代<select disabled={busy || networkBusy} value={iterations} onChange={e => {setIterations(Number(e.target.value));setAnalysis(null);setNetworkResult(null);}}>
            <option value={1}>1轮</option><option value={2}>2轮</option><option value={3}>3轮</option>
          </select></label>
        </div>
        <div className="pmss-toolbar">
          <p>最多 {inspection.max_segments} 段 · 24时段同一曲线 · 报价范围需服从课程规则</p>
          <button className="pmss-run-button" type="button" disabled={busy || networkBusy} onClick={() => void run()}>
            {activeTask==="optimize" ? "正在计算..." : "生成分段报价"} <ArrowRight size={16}/>
          </button>
        </div>
        {analysis && <>
          <div className="pmss-summary">
            <Metric label="原报价模拟利润" value={numeric(analysis.baseline.total_profit, 2)} detail="单区域模型"/>
            <Metric label="推荐模拟利润" value={numeric(analysis.recommended.total_profit, 2)} detail="不是 PMSS 真实收益"/>
            <Metric label="基准中标量 MAE" value={analysis.baseline_backtest?.power_mae_mw == null ? "无历史对照" :
              numeric(analysis.baseline_backtest.power_mae_mw, 2) + " MW"} detail="原报价模型与真实出清偏差"/>
          </div>
          <div className="pmss-result-toolbar"><h4>本地推荐分段</h4>
            <button type="button" onClick={() => saveReview(analysis)}><Download size={15}/> 下载审核 JSON</button>
          </div>
          <div className="pmss-table-scroll"><table className="pmss-table">
            <thead><tr><th>段号</th><th>起始出力</th><th>结束出力</th><th>本段容量</th><th>报价</th></tr></thead>
            <tbody>{analysis.recommended.segments.map((s, i) => <tr key={i}>
              <td>{i + 1}</td><td>{numeric(s.start_power, 2)} MW</td>
              <td>{numeric(s.end_power, 2)} MW</td>
              <td>{numeric(s.end_power - s.start_power, 2)} MW</td>
              <td><strong>{numeric(s.price, 2)}</strong></td>
            </tr>)}</tbody>
          </table></div>
          {analysis.baseline_backtest && <div className="pmss-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={comparison} margin={{top:16,right:16,bottom:2,left:-10}}>
                <CartesianGrid stroke="var(--ta-border)" vertical={false}/>
                <XAxis dataKey="period" tick={axisStyle} axisLine={false} tickLine={false}/>
                <YAxis tick={axisStyle} axisLine={false} tickLine={false}/>
                <Tooltip contentStyle={tooltipStyle}/><Legend verticalAlign="top" height={32}/>
                <Line dataKey="actual" name="PMSS 真实中标" isAnimationActive={false} stroke="#039855" strokeWidth={2.5} dot={false}/>
                <Line dataKey="original" name="原报价本地模拟" isAnimationActive={false} stroke="#98a2b3" strokeWidth={2} dot={false}/>
                <Line dataKey="recommended" name="新报价本地模拟" isAnimationActive={false} stroke="#465fff" strokeWidth={2.5} dot={false}/>
              </LineChart>
            </ResponsiveContainer>
          </div>}
          <OptimizationHourReview analysis={analysis}/>
          <p className="pmss-footnote">新推荐没有在 PMSS 中提交或出清。历史 MAE 只评价原报价的模型拟合，不是新报价的真实收益保证。</p>
        </>}
      </div>
      <div className="pmss-panel">
        <div className="pmss-panel-head">
          <div>
            <small>04 / NETWORK-CONSTRAINED VALIDATION</small>
            <h3>DC 网络约束复算</h3>
            <p>用核实的节点负荷、机组接入母线、线路电抗与额定 MW 进行逐小时线性网络出清。</p>
          </div>
          <span className="pmss-state-label">本地 DC-OPF</span>
        </div>
        {inspection.dc_grid_available ? <>
          <p className="pmss-footnote">已加载 {inspection.dc_grid_buses} 个真实母线、
            {inspection.dc_grid_lines} 条真实线路。只评估原始报价及当前单区域模型的候选报价，
            不代表 PMSS 真实重出清，也不包含多时段机组启停、爬坡和备用约束。</p>
          {!analysis && <p className="pmss-footnote">请先生成五段报价，再点击网络约束对照。</p>}
          <div className="pmss-toolbar">
            <p>逐时段 DC 潮流和线限额约束；节点边际电价来自本地线性规划。</p>
            <button className="pmss-run-button" type="button"
              disabled={!analysis || busy || networkBusy}
              onClick={() => void runNetwork()}>
              {networkBusy ? "网络模型计算中..." : "运行真实拓扑网络对照"}
              <ArrowRight size={16}/>
            </button>
          </div>
          {networkResult && <>
            <div className="pmss-summary">
              <Metric label="原报价 DC 模拟发电量"
                value={numeric(networkResult.baseline.total_accepted_mwh, 2) + " MWh"}
                detail="真实拓扑 / 模拟结果"/>
              <Metric label="原报价 DC 模拟收益"
                value={numeric(networkResult.baseline.total_profit, 2)}
                detail="单独模型的假定边际成本口径"/>
              <Metric label="候选曲线 DC 模拟收益"
                value={networkResult.recommended
                  ? numeric(networkResult.recommended.total_profit, 2) : "不可行"}
                detail="不是 PMSS 结算收入"/>
            </div>
            {networkResult.historical_grid_audit && <>
              <div className="pmss-result-toolbar">
                <h4>PMSS 已出清历史数据一致性 · {networkResult.historical_grid_audit.case_date}</h4>
                <span className="pmss-state-label">仅单日基准回测</span>
              </div>
              <div className="pmss-summary">
                <Metric label="真实节点有功平衡残差 MAE"
                  value={networkResult.historical_grid_audit.bus_balance_mae_mw == null
                    ? "无完整数据"
                    : numeric(networkResult.historical_grid_audit.bus_balance_mae_mw, 2) + " MW"}
                  detail={networkResult.historical_grid_audit.balanced_hour_count + "/24 个完整时段"}/>
                <Metric label="模型 vs PMSS 节点电价 MAE"
                  value={networkResult.historical_grid_audit.modeled_nodal_price_mae == null
                    ? "无数据"
                    : numeric(networkResult.historical_grid_audit.modeled_nodal_price_mae, 2)}
                  detail="价格计费口径仍需校准"/>
                <Metric label="模型 vs PMSS 线路绝对潮流 MAE"
                  value={networkResult.historical_grid_audit.modeled_abs_flow_mae_mw == null
                    ? "无数据"
                    : numeric(networkResult.historical_grid_audit.modeled_abs_flow_mae_mw, 2) + " MW"}
                  detail="仅比较潮流幅值"/>
              </div>
              <div className="pmss-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={networkResult.historical_grid_audit.hours}
                    margin={{top:16,right:20,bottom:4,left:-9}}>
                    <CartesianGrid stroke="var(--ta-border)" vertical={false}/>
                    <XAxis dataKey="period" tick={axisStyle} axisLine={false} tickLine={false}/>
                    <YAxis yAxisId="mw" tick={axisStyle} axisLine={false} tickLine={false}/>
                    <YAxis yAxisId="price" orientation="right" tick={axisStyle}
                      axisLine={false} tickLine={false}/>
                    <Tooltip contentStyle={tooltipStyle}/>
                    <Legend verticalAlign="top" height={32}/>
                    <Line yAxisId="mw" type="monotone" dataKey="observed_bus_balance_mae_mw"
                      name="PMSS节点平衡残差 MW" stroke="#f59e0b"
                      strokeWidth={2.4} dot={false} isAnimationActive={false}/>
                    <Line yAxisId="price" type="monotone" dataKey="modeled_nodal_price_mae"
                      name="DC模型 vs PMSS 价差 MAE" stroke="#465fff"
                      strokeWidth={2.4} dot={false} isAnimationActive={false}/>
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="pmss-footnote">
                全节点模型电价与 PMSS 完全一致的时段：
                <strong>{networkResult.historical_grid_audit.modeled_price_matching_hours}/24</strong>；
                电价不一致时段：
                {networkResult.historical_grid_audit.modeled_price_mismatch_periods.join("、") || "无"}。
                DC 模型节点价格峰值：
                {networkResult.historical_grid_audit.modeled_peak_node_price == null
                  ? "—" : numeric(networkResult.historical_grid_audit.modeled_peak_node_price, 2)}；
                PMSS 历史节点价格峰值：
                {networkResult.historical_grid_audit.observed_peak_node_price == null
                  ? "—" : numeric(networkResult.historical_grid_audit.observed_peak_node_price, 2)}。
                当前只定位可能的结算定价规则差异，没有据此自动裁剪或调整候选策略的电价。
              </p>
              <p className="pmss-footnote">
                本报告只对已提交的原始报价做同一天的事后核验，
                不用历史价格替代未来预测。线路方向按读取的两端节点和原始潮流符号计算，
                并额外核对反向符号；节点有功平衡残差不等同于违规或线路过载。
                这还不是跨日期留出验证。
              </p>
              <div className="pmss-table-scroll">
                <table className="pmss-table">
                  <thead><tr><th>历史残差较大节点</th><th>逐时段平均平衡残差</th><th>覆盖时段</th></tr></thead>
                  <tbody>{networkResult.historical_grid_audit.worst_bus_balance.slice(0, 5).map(item =>
                    <tr key={item.element_id}><td>{item.element_id}</td>
                      <td>{numeric(item.mae, 2)} MW</td><td>{item.points}/24</td></tr>
                  )}</tbody>
                </table>
              </div>
            </>}
            {!networkResult.historical_grid_audit && <p className="pmss-footnote">
              尚不能给出严格对应的历史网络回测。
              {networkResult.historical_unavailable_reason || "缺少完整 PMSS 历史节点/线路结果"}
            </p>}
            <p className="pmss-footnote">
              原报价约束活跃时段：{networkResult.baseline.hours_with_binding_lines}/24；
              线路峰值负载比：{numeric(networkResult.baseline.max_line_utilization * 100, 2)}%。
              模型忽略网损和机组跨时段约束，节点电价不保证重现 PMSS。
            </p>
            {networkResult.recommended_error && <div className="pmss-error">
              候选报价无法在当前 DC 模型中完成出清：{networkResult.recommended_error}
            </div>}
            <div className="pmss-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={dcHours} margin={{top:16,right:18,bottom:4,left:-9}}>
                  <CartesianGrid stroke="var(--ta-border)" vertical={false}/>
                  <XAxis dataKey="period" tick={axisStyle} axisLine={false} tickLine={false}/>
                  <YAxis tick={axisStyle} axisLine={false} tickLine={false}/>
                  <Tooltip contentStyle={tooltipStyle}/><Legend verticalAlign="top" height={32}/>
                  <Line dataKey="observedPMSS" name="PMSS 已出清历史中标 MW"
                    isAnimationActive={false} dot={false} stroke="#039855" strokeWidth={2.6}/>
                  <Line dataKey="originalDC" name="原报价 DC 模型 MW"
                    isAnimationActive={false} dot={false} stroke="#98a2b3" strokeWidth={2.1}/>
                  <Line dataKey="proposedDC" name="候选报价 DC 模型 MW"
                    isAnimationActive={false} dot={false} stroke="#465fff" strokeWidth={2.5}/>
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="pmss-footnote">该对照可以发现候选在本地线性网络模型中的潮流与中标变化，
              但不能证明策略在老师 PMSS 或真实电力市场中安全、最优或可执行。</p>
          </>}
        </> : <p className="pmss-footnote">
          当前快照没有 `dcNetwork` 网络参数。请从可信服务器使用
          `scripts/merge_pmss_grid.py` 将只读节点、线路和机组接入数据合入脱敏快照，
          缺少经核实的电抗或额定 MW 时禁止猜测。
        </p>}
      </div>
      {snapshot && <PMSSCandidateDispatchPanel
        key={fileName + ":" + target}
        snapshot={snapshot}
        inspection={inspection}
        target={target}
        analysis={analysis}
        rankResult={rankResult}
        otherBusy={busy || networkBusy || rankBusy}
      />}
    </>}
    <PMSSHoldoutGatePanel/>
  </section>;
}
