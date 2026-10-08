import { useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, ChevronLeft, ChevronRight, Clock3, Download, Factory, Search, TrendingUp } from "lucide-react";
import { csvExport, numeric, type PMSSInspection, type PMSSOptimization } from "./types";
import "./pmss-insights.css";

const axis = { fontSize: 11, fill: "#98a2b3" };
const tooltip = {
  backgroundColor: "var(--ta-panel)",
  color: "var(--ta-ink)",
  border: "1px solid var(--ta-border)",
  borderRadius: 10,
  fontSize: 12,
  boxShadow: "0 12px 30px rgba(16,24,40,.08)",
};
const formatValue = (value: unknown) => typeof value === "number" ? numeric(value, 2) : String(value ?? "—");
const getHour = (period: number) => `第 ${period} 时段`;

export function MarketExplorer({inspection}: {inspection: PMSSInspection}) {
  const [hour, setHour] = useState(1);
  const [query, setQuery] = useState("");
  const [order, setOrder] = useState<"unit" | "capacity" | "cost">("unit");
  const load = inspection.load_mw;
  const observed = inspection.network?.hourly ?? [];
  const rows = useMemo(() => load.map((demand, index) => ({
    hour: index + 1,
    demand,
    price: observed[index]?.mean_lmp ?? null,
    spread: observed[index]?.lmp_spread ?? null,
  })), [load, observed]);
  const selected = rows[Math.max(0, hour - 1)];
  const average = load.length ? load.reduce((a,b) => a+b, 0)/load.length : 0;
  const peak = Math.max(0, ...load);
  const filteredUnits = useMemo(() => inspection.units
    .filter(u => `${u.name} ${u.unit_id} ${u.unit_type}`.toLowerCase().includes(query.toLowerCase()))
    .sort((a,b) => order === "capacity"
      ? b.capacity_mw - a.capacity_mw
      : order === "cost"
        ? a.running_cost - b.running_cost
        : a.unit_id.localeCompare(b.unit_id)),
  [inspection.units, query, order]);

  const chooseHour = (value: number) => setHour(Math.max(1, Math.min(rows.length || 1, value)));
  return <div className="pmss-explorer">
    <div className="pmss-panel">
      <div className="pmss-panel-head">
        <div><small>24H / MARKET LOAD</small><h3>24 时段市场负荷曲线</h3>
          <p>来自导入快照的场景输入；图表不会自行预测未来负荷。</p></div>
        <span className="pmss-state-label"><Activity size={14}/> 快照数据</span>
      </div>
      <div className="pmss-load-chart" role="img" aria-label="按时段显示的市场负荷变化">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{top:15,right:15,bottom:5,left:-8}}>
            <defs><linearGradient id="pmssLoadFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#465fff" stopOpacity={0.19}/>
              <stop offset="96%" stopColor="#465fff" stopOpacity={0.01}/>
            </linearGradient></defs>
            <CartesianGrid vertical={false} stroke="var(--ta-border)" strokeDasharray="3 5"/>
            <XAxis dataKey="hour" tick={axis} tickMargin={12} axisLine={false} tickLine={false} tickCount={7}/>
            <YAxis tick={axis} axisLine={false} tickLine={false} width={64} tickFormatter={v=>numeric(v)}/>
            <Tooltip contentStyle={tooltip} formatter={formatValue} labelFormatter={label=>getHour(Number(label))}/>
            <ReferenceLine x={hour} stroke="#465fff" strokeDasharray="4 5"/>
            <Area isAnimationActive={false} type="monotone" dataKey="demand" name="负荷 MW" stroke="#465fff" strokeWidth={2.7} fill="url(#pmssLoadFill)" activeDot={{r:5}}/>
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="pmss-hour-selector">
        <div className="pmss-hour-controls">
          <div><span>时段检查器</span><strong>{getHour(hour)} / {rows.length} 时段</strong></div>
          <div className="pmss-hour-buttons">
            <button type="button" aria-label="上一个时段" disabled={hour<=1} onClick={()=>chooseHour(hour-1)}><ChevronLeft size={16}/></button>
            <button type="button" aria-label="下一个时段" disabled={hour>=rows.length} onClick={()=>chooseHour(hour+1)}><ChevronRight size={16}/></button>
          </div>
        </div>
        <div className="pmss-hour-track" role="group" aria-label="选择市场时段">
          {rows.map(row => <button type="button" key={row.hour} aria-pressed={hour===row.hour}
            className={hour===row.hour?"active":""} onClick={()=>chooseHour(row.hour)} title={getHour(row.hour)}>
            {String(row.hour).padStart(2,"0")}
          </button>)}
        </div>
        <div className="pmss-hour-facts">
          <div><span>本时段负荷</span><strong>{selected ? numeric(selected.demand,2)+" MW" : "—"}</strong></div>
          <div><span>24时段平均负荷</span><strong>{numeric(average,2)} MW</strong></div>
          <div><span>24时段峰值负荷</span><strong>{numeric(peak,2)} MW</strong></div>
          <div><span>历史节点均价</span><strong>{selected?.price==null?"无历史数据":numeric(selected.price,2)}</strong></div>
        </div>
      </div>
    </div>
    <div className="pmss-panel">
      <div className="pmss-panel-head">
        <div><small>GENERATION / PROFILE</small><h3>机组档案</h3><p>查看快照中已识别的机组容量和成本参数。此处不修改老师平台原始申报。</p></div>
        <span className="pmss-state-label"><Factory size={14}/> {inspection.units.length} 台机组</span>
      </div>
      <div className="pmss-unit-toolbar">
        <label className="pmss-unit-search"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索机组名称或编号" aria-label="搜索 PMSS 机组"/></label>
        <label className="pmss-unit-order">排序
          <select value={order} onChange={e=>setOrder(e.target.value as typeof order)}>
            <option value="unit">机组编号</option><option value="capacity">容量从大到小</option><option value="cost">成本从低到高</option>
          </select>
        </label>
      </div>
      <div className="pmss-table-scroll">
        <table className="pmss-table">
          <thead><tr><th>机组</th><th>类型</th><th>申报容量</th><th>最小出力</th><th>运行成本</th></tr></thead>
          <tbody>{filteredUnits.map(u=><tr key={u.unit_id}>
            <td><div className="pmss-unit-identity"><span className="pmss-unit-avatar">{u.unit_id.slice(0,2)}</span><div><strong>{u.name||u.unit_id}</strong><small>{u.unit_id}</small></div></div></td>
            <td>{u.unit_type || "未标记"}</td>
            <td>{numeric(u.capacity_mw,2)} MW</td>
            <td>{numeric(u.min_power_mw,2)} MW</td>
            <td>{numeric(u.running_cost,2)}</td>
          </tr>)}
          {!filteredUnits.length && <tr><td colSpan={5} className="pmss-unit-empty">未找到匹配机组</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  </div>;
}

type Measure = "accepted" | "profit" | "price";
const measures: {id:Measure; label:string}[]=[
  {id:"accepted",label:"中标电量"},
  {id:"profit",label:"本地模拟利润"},
  {id:"price",label:"本地出清价格"},
];
export function OptimizationHourReview({analysis}: {analysis: PMSSOptimization}) {
  const [measure,setMeasure]=useState<Measure>("accepted");
  const [hour,setHour]=useState(1);
  const hours = analysis.recommended.hours;
  const observed = analysis.baseline_backtest?.hours || [];
  const data = hours.map((r,index)=>({
    hour:r.period,accepted:r.target_accepted_mw,profit:r.target_profit,
    price:r.clearing_price,
    actual:observed[index]?.observed_accepted_mw??null,
    baseline:observed[index]?.surrogate_accepted_mw??null,
  }));
  const picked=data[Math.min(Math.max(0,hour-1),data.length-1)];
  const hasReference=analysis.baseline_backtest!=null;
  const exportHours=()=>csvExport("powerbid_pmss_local_hourly_review.csv",
    ["时段","本地推荐中标MW","本地模拟利润","本地出清价格","PMSS历史实际中标MW","原报价本地模拟中标MW"],
    data.map(v=>[v.hour,v.accepted,v.profit,v.price,v.actual,v.baseline])
  );
  return <section className="pmss-panel pmss-review">
    <div className="pmss-panel-head">
      <div><small>HOURLY / LOCAL MODEL</small><h3>24 时段推荐策略分析</h3>
        <p>本地代理模型的计算输出，不是 PMSS 对新报价的重出清。</p>
      </div>
      <button type="button" className="pmss-review-export" onClick={exportHours}><Download size={16}/> 导出 24 时段 CSV</button>
    </div>
    <div className="pmss-review-tabs" role="group" aria-label="选择分析指标">
      {measures.map(m=><button type="button" key={m.id} aria-pressed={measure===m.id}
        className={measure===m.id?"active":""} onClick={()=>setMeasure(m.id)}>{m.label}</button>)}
    </div>
    <div className="pmss-review-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{top:16,right:14,bottom:0,left:-6}}>
          <CartesianGrid stroke="var(--ta-border)" strokeDasharray="3 5" vertical={false}/>
          <XAxis dataKey="hour" tick={axis} tickMargin={10} axisLine={false} tickLine={false}/>
          <YAxis tick={axis} axisLine={false} tickLine={false} width={68} tickFormatter={v=>numeric(v)}/>
          <Tooltip contentStyle={tooltip} formatter={formatValue} labelFormatter={label=>getHour(Number(label))}/>
          <ReferenceLine x={hour} stroke="#465fff" strokeDasharray="5 4"/>
          <Line type="monotone" name={measures.find(m=>m.id===measure)?.label} dataKey={measure} stroke="#465fff"
            strokeWidth={2.7} dot={false} activeDot={{r:5}} isAnimationActive={false}/>
          {measure==="accepted" && hasReference && <>
            <Line type="monotone" name="PMSS 历史真实中标（原报价）" dataKey="actual" stroke="#039855"
              strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false}/>
            <Line type="monotone" name="原报价本地模拟" dataKey="baseline" stroke="#98a2b3"
              strokeWidth={1.7} dot={false} isAnimationActive={false}/>
          </>}
        </LineChart>
      </ResponsiveContainer>
    </div>
    <div className="pmss-review-slider">
      <div className="pmss-review-slider-title"><Clock3 size={15}/><span>{getHour(hour)}</span>
        <span className="pmss-review-note">左右拖动检查各时段</span></div>
      <input type="range" min={1} max={Math.max(1,hours.length)} value={hour}
        onChange={e=>setHour(Number(e.target.value))} aria-label="选择推荐策略时段"/>
    </div>
    {picked && <div className="pmss-review-facts">
      <div><span>推荐模拟中标</span><strong>{numeric(picked.accepted,2)} MW</strong></div>
      <div><span>推荐模拟利润</span><strong>{numeric(picked.profit,2)}</strong></div>
      <div><span>本地出清价格</span><strong>{picked.price==null?"无出清":numeric(picked.price,2)}</strong></div>
      <div><span>PMSS 历史真实中标（原报价）</span><strong>{picked.actual==null?"未提供":numeric(picked.actual,2)+" MW"}</strong></div>
    </div>}
    <p className="pmss-footnote"><TrendingUp size={14}/> 如果看到真实历史曲线，它仅是原报价的历史对照数据；蓝线为新报价的本地预测，二者不可直接当作同一次 PMSS 出清结果。</p>
  </section>;
}
