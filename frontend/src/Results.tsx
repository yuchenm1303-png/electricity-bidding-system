import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import { ArrowRight, BarChart3, CircleCheck, ClipboardList, Download, Info, Layers, TrendingUp, Zap } from "lucide-react";
import { useReducedMotion } from "./useReducedMotion";
import { asSingle, asRisk, numeric, csvExport, type Report, type SingleTrial, type RiskTrial } from "./types";

type Props = {
  report: Report | null;
  stale: boolean;
  running: boolean;
  onRun: () => void;
  compact?: boolean;
};
const fmt = (val: unknown) => typeof val === "number" ? numeric(val, 2) : String(val ?? "—");
const tooltipStyle = {
  backgroundColor: "#ffffff",
  border: "1px solid #e4e7ec",
  borderRadius: 10,
  color: "#344054",
  fontSize: 12,
  padding: "10px 13px",
  boxShadow: "0 16px 36px rgba(16,24,40,.1)",
};
const axis = { fill: "#8999a8", fontSize: 11 };
const chartMargin = { top: 10, right: 15, bottom: 0, left: -10 };

export function Recommendation({ report, stale, onRun, running }: Props) {
  if (!report) return <section className="recommendation-panel before-report">
    <div className="panel-kicker">OPTIMIZATION RESULT</div>
    <div className="recommendation-empty"><div className="recommendation-illustration"><TrendingUp size={27}/></div>
      <h3>等待首次策略分析</h3><p>运行模型后，这里会显示推荐报价、目标机组预计利润和市场出清表现。</p></div>
    <button className="ghost-cta" onClick={onRun} disabled={running}>开始分析 <ArrowRight size={15}/></button>
  </section>;
  const best = report.mode === "single" ? asSingle(report.best) : asRisk(report.best);
  const profit = report.mode === "single" ? asSingle(best).profit : asRisk(best).expected_profit;
  const mw = report.mode === "single" ? asSingle(best).accepted_mw : asRisk(best).expected_accepted_mw;
  return <section className="recommendation-panel result-ready">
    <div className="recommendation-top"><span className="panel-kicker">RECOMMENDED BID</span>
      <span className={"status-chip " + (stale ? "warning" : "success")}>{stale ? "待更新" : "分析完成"}</span></div>
    <div className="recommendation-price"><span>{numeric(best.bid_price, 2)}</span><small>报价 / MWh</small></div>
    <div className="recommendation-dash"/>
    <div className="recommendation-facts">
      <div><span>预计利润</span><strong>{numeric(profit, 2)}</strong></div>
      <div><span>预计中标</span><strong>{numeric(mw, 2)} MW</strong></div>
    </div>
    <div className="recommendation-foot"><CircleCheck size={15}/>{stale ? "参数已修改，请重新运行" : `已评估 ${report.count} 个候选报价`}</div>
  </section>;
}
function MetricCard({ icon, label, value, note, accent }: { icon: React.ReactNode; label: string; value: string; note: string; accent?: boolean }) {
  return <div className={"result-metric " + (accent ? "accent" : "")}>
    <div className="result-metric-top"><span>{label}</span>{icon}</div>
    <strong>{value}</strong><small>{note}</small>
  </div>;
}
function HeaderLabel({ eyebrow, title, note }: { eyebrow: string; title: string; note: string }) {
  return <div className="result-section-heading"><div><span className="panel-kicker">{eyebrow}</span>
    <h2>{title}</h2><p>{note}</p></div></div>;
}
function EmptyReport({ running, onRun }: Pick<Props, "running" | "onRun">) {
  return <section className="report-empty">
    <div className="report-empty-art"><BarChart3 size={33}/></div>
    <span className="panel-kicker">SIMULATION WORKSPACE</span>
    <h2>让数据开始说话</h2>
    <p>市场参数准备就绪后，运行一次报价优化，即可查看推荐策略、报价收益曲线和完整试算明细。</p>
    <button className="primary-button" onClick={onRun} disabled={running}><Zap size={16}/>{running ? "正在计算..." : "运行报价分析"}<ArrowRight size={15}/></button>
  </section>;
}
export function ResultsContent({ report, stale, running, onRun, compact = false }: Props) {
  const reducedMotion = useReducedMotion();
  if (!report) return <EmptyReport running={running} onRun={onRun}/>;
  const risk = report.mode === "risk";
  const best = report.best;
  const single = asSingle(best);
  const stress = asRisk(best);
  const data = report.trials;
  return <div className={"results-content " + (compact ? "compact" : "")}>
    <HeaderLabel eyebrow="03 / DECISION OUTPUT" title={risk ? "风险策略分析" : "报价决策结果"}
      note="基于当前教学模拟环境测算，所有数据均来自实际优化计算。"/>
    {stale && <div className="stale-banner"><Info size={16}/> 参数已经发生变化。当前显示上次分析结果，重新运行后更新。<button onClick={onRun}>重新分析 <ArrowRight size={14}/></button></div>}
    <div className="result-metrics">
      <MetricCard accent icon={<Zap size={17}/>} label="推荐报价" value={numeric(best.bid_price, 2)} note="价格 / MWh"/>
      <MetricCard icon={<TrendingUp size={17}/>} label={risk ? "期望利润" : "预计利润"}
        value={numeric(risk ? stress.expected_profit : single.profit, 2)} note="按当前时段计算"/>
      <MetricCard icon={<Layers size={17}/>} label={risk ? "下行情景利润" : "出清价格"}
        value={risk ? numeric(stress.downside_profit, 2) : single.clearing_price == null ? "—" : numeric(single.clearing_price, 2)} note={risk ? "最差部分情景均值" : "统一出清价"}/>
      <MetricCard icon={<CircleCheck size={17}/>} label={risk ? "预计中标量" : "预计中标量"}
        value={numeric(risk ? stress.expected_accepted_mw : single.accepted_mw, 2) + " MW"} note="目标机组"/>
    </div>
    <div className="chart-grid">
      <div className="chart-card primary-chart">
        <div className="chart-card-head"><div><h3>{risk ? "收益情景比较" : "报价收益曲线"}</h3><p>{risk ? "期望收益、下行收益与最差情景" : "分析不同报价对应的目标机组利润"}</p></div><span className="chart-tag">PROFIT</span></div>
        <div className="chart-canvas">
          <ResponsiveContainer width="100%" height="100%">
            {risk ? <LineChart data={data} margin={chartMargin}>
              <CartesianGrid stroke="#e8edf4" vertical={false} strokeDasharray="3 4"/>
              <XAxis dataKey="bid_price" tick={axis} axisLine={false} tickLine={false} tickMargin={12}/>
              <YAxis tick={axis} axisLine={false} tickLine={false} tickFormatter={v => numeric(v)} width={65}/>
              <Tooltip contentStyle={tooltipStyle} formatter={fmt} />
              <Legend verticalAlign="top" height={38} iconType="circle" wrapperStyle={{fontSize:11,color:"#a3b5be"}} />
              <ReferenceLine x={best.bid_price} stroke="#465fff" strokeDasharray="4 5"/>
              <Line isAnimationActive={!reducedMotion} animationDuration={560} animationEasing="ease-out" type="monotone" dataKey="expected_profit" name="期望利润" stroke="#465fff" strokeWidth={2.5} dot={false} activeDot={{r:5}}/>
              <Line isAnimationActive={!reducedMotion} animationDuration={560} animationEasing="ease-out" type="monotone" dataKey="downside_profit" name="下行利润" stroke="#99a6ff" strokeWidth={2} dot={false}/>
              <Line isAnimationActive={!reducedMotion} animationDuration={560} animationEasing="ease-out" type="monotone" dataKey="worst_profit" name="最差利润" stroke="#efa6b3" strokeWidth={1.7} dot={false}/>
            </LineChart> : <AreaChart data={data} margin={chartMargin}>
              <defs><linearGradient id="profitFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#465fff" stopOpacity={0.26}/><stop offset="95%" stopColor="#465fff" stopOpacity={0}/></linearGradient></defs>
              <CartesianGrid stroke="#e8edf4" vertical={false} strokeDasharray="3 4"/>
              <XAxis dataKey="bid_price" tick={axis} axisLine={false} tickLine={false} tickMargin={12}/>
              <YAxis tick={axis} axisLine={false} tickLine={false} tickFormatter={v => numeric(v)} width={65}/>
              <Tooltip contentStyle={tooltipStyle} formatter={fmt} />
              <ReferenceLine x={best.bid_price} stroke="#465fff" strokeDasharray="4 5" label={{value:"推荐",position:"insideTop",fill:"#465fff",fontSize:11}}/>
              <Area isAnimationActive={!reducedMotion} animationDuration={560} animationEasing="ease-out" type="monotone" dataKey="profit" name="利润" stroke="#465fff" strokeWidth={2.8} fill="url(#profitFill)" activeDot={{r:5}}/>
            </AreaChart>}
          </ResponsiveContainer>
        </div>
        <div className="chart-axis-label">候选报价 / MWh</div>
      </div>
      <div className="chart-card secondary-chart">
        <div className="chart-card-head"><div><h3>{risk ? "风险综合评分" : "中标电量变化"}</h3><p>{risk ? "结合期望与下行利润的得分" : "报价变化对出清电量的影响"}</p></div><span className="chart-tag">{risk ? "RISK" : "VOLUME"}</span></div>
        <div className="chart-canvas">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={chartMargin}>
              <CartesianGrid stroke="#e8edf4" vertical={false} strokeDasharray="3 4"/>
              <XAxis dataKey="bid_price" tick={axis} axisLine={false} tickLine={false} tickMargin={12}/>
              <YAxis tick={axis} axisLine={false} tickLine={false} width={58} tickFormatter={v => numeric(v)}/>
              <Tooltip contentStyle={tooltipStyle} formatter={fmt}/>
              <ReferenceLine x={best.bid_price} stroke="#465fff" strokeDasharray="4 5"/>
              <Line isAnimationActive={!reducedMotion} animationDuration={560} animationEasing="ease-out" dataKey={risk ? "score" : "accepted_mw"} name={risk ? "风险得分" : "中标 MW"} type="monotone"
                stroke="#465fff" strokeWidth={2.7} dot={false} activeDot={{r:5}}/>
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="chart-axis-label">候选报价 / MWh</div>
      </div>
    </div>
    {!compact && <TrialDetails report={report}/>}
  </div>;
}
export function TrialDetails({ report }: { report: Report | null }) {
  if (!report) return <div className="trial-placeholder"><ClipboardList size={24}/><h3>暂无试算明细</h3><p>运行报价分析后即可查看完整结果。</p></div>;
  const risk = report.mode === "risk";
  const rows = risk
    ? (report.trials as RiskTrial[]).map(r => [r.bid_price, r.expected_profit, r.downside_profit, r.worst_profit, r.expected_accepted_mw, r.feasible_probability, r.score])
    : (report.trials as SingleTrial[]).map(r => [r.bid_price, r.clearing_price, r.accepted_mw, r.revenue, r.variable_cost, r.profit, r.feasible]);
  const labels = risk
    ? ["报价", "期望利润", "下行利润", "最差利润", "中标MW", "可行概率", "风险得分"]
    : ["报价", "出清价格", "中标MW", "收入", "变动成本", "利润", "可行"];
  const exportRows = rows.map(r => r.map(v => v == null ? "" : typeof v === "boolean" ? (v ? "是" : "否") : v));
  return <section className="trials-panel">
    <div className="panel-head"><div><span className="panel-kicker">ANALYSIS RECORDS</span><h2>完整试算明细</h2><p>{report.count} 个候选报价 · 支持导出 CSV</p></div>
      <button type="button" className="secondary-button" onClick={() => csvExport(
        risk ? "powerbid_risk_analysis.csv" : "powerbid_single_analysis.csv", labels, exportRows
      )}><Download size={15}/> 导出结果</button></div>
    <div className="table-scroll trial-scroll"><table className="trials-table"><thead><tr>{labels.map(l => <th key={l}>{l}</th>)}</tr></thead>
      <tbody>{rows.map((row, i) => <tr key={i} className={row[0] === report.best.bid_price ? "is-best" : ""}>
        {row.map((value, j) => <td key={j}>{typeof value === "boolean" ? (value ? "是" : "否") :
          typeof value === "number" ? (risk && j === 5 ? (value * 100).toFixed(1) + "%" : numeric(value, 2)) : value ?? "—"}
        </td>)}</tr>)}</tbody></table></div>
    {risk && <div className="outcomes-block"><div className="outcomes-heading"><h3>推荐报价 · 压力情景</h3><small>九组等权模拟情景</small></div>
      <div className="table-scroll"><table className="trials-table"><thead><tr><th>场景</th><th>概率</th><th>出清价</th><th>中标量 MW</th><th>利润</th><th>可行</th></tr></thead>
        <tbody>{asRisk(report.best).outcomes.map(o => <tr key={o.name}><td>{o.name}</td><td>{(o.probability * 100).toFixed(1)}%</td>
          <td>{o.clearing_price == null ? "—" : numeric(o.clearing_price,2)}</td><td>{numeric(o.accepted_mw,2)}</td><td>{numeric(o.profit,2)}</td><td>{o.feasible ? "是" : "否"}</td></tr>)}</tbody></table></div>
    </div>}
  </section>;
}
