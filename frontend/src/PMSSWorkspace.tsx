import { useRef, useState, type ChangeEvent } from "react";
import { Activity, ArrowRight, Database, Download, FileJson2, ShieldCheck, UploadCloud } from "lucide-react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { inspectPMSS, optimizePMSS } from "./api";
import { numeric, type PMSSInspection, type PMSSOptimization } from "./types";
import { MarketExplorer, OptimizationHourReview } from "./PMSSInsights";
import "./pmss-studio.css";

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

export function PMSSWorkspace() {
  const picker = useRef<HTMLInputElement | null>(null);
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);
  const [inspection, setInspection] = useState<PMSSInspection | null>(null);
  const [analysis, setAnalysis] = useState<PMSSOptimization | null>(null);
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
    if (busy) return;
    setInspection(null); setSnapshot(null); setAnalysis(null); setError(""); setFileName("");
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
  const onDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!busy && event.dataTransfer.files.length) {
      void importFile(event.dataTransfer.files[0]);
    }
  };

  const run = async () => {
    if (!snapshot || !target || busy) return;
    if (![minimum, maximum, step].every(Number.isFinite) ||
        minimum < 0 || maximum > 10000 || maximum < minimum || step <= 0) {
      setError("报价范围必须为 0–10000，且步长应大于零");
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
      <button className="pmss-import-button" type="button" disabled={busy} onClick={() => picker.current?.click()}>
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
    {!inspection && <div className="pmss-empty" onDragOver={e=>e.preventDefault()} onDrop={onDrop}>
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
      <MarketExplorer inspection={inspection}/>
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
        <p className="pmss-footnote">非零影子价格不是线路过载证明。当前尚未建立真实网络拓扑、容量约束与节点机组映射。</p>
      </div>}
      <div className="pmss-panel">
        <div className="pmss-panel-head"><div><small>03 / FIVE-SEGMENT STRATEGY</small><h3>五段价格—电量曲线搜索</h3>
          <p>复用本地单区域统一价引擎；生成的是教学模拟报价，不是 PMSS 重出清。</p></div>
          <span className="pmss-state-label">本地模拟</span>
        </div>
        <div className="pmss-controls">
          <label>目标机组<select disabled={busy} value={target} onChange={e => {setTarget(e.target.value);setAnalysis(null);}}>
            {inspection.units.map(item => <option key={item.unit_id} value={item.unit_id}>{item.name}</option>)}
          </select></label>
          <label>最低报价<input type="number" disabled={busy} min="0" max="10000" value={minimum} onChange={e => {setMinimum(Number(e.target.value));setAnalysis(null);}}/></label>
          <label>最高报价<input type="number" disabled={busy} min="0" max="10000" value={maximum} onChange={e => {setMaximum(Number(e.target.value));setAnalysis(null);}}/></label>
          <label>报价步长<input type="number" disabled={busy} min="1" value={step} onChange={e => {setStep(Number(e.target.value));setAnalysis(null);}}/></label>
          <label>局部迭代<select disabled={busy} value={iterations} onChange={e => {setIterations(Number(e.target.value));setAnalysis(null);}}>
            <option value={1}>1轮</option><option value={2}>2轮</option><option value={3}>3轮</option>
          </select></label>
        </div>
        <div className="pmss-toolbar">
          <p>最多 {inspection.max_segments} 段 · 24时段同一曲线 · 报价范围需服从课程规则</p>
          <button className="pmss-run-button" type="button" disabled={busy} onClick={() => void run()}>
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
    </>}
  </section>;
}
