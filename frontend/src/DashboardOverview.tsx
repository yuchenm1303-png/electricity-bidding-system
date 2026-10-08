import { useMemo } from "react";
import { useReducedMotion } from "./useReducedMotion";
import { Activity, BarChart3, Boxes, TrendingUp, Zap, ArrowUpRight, Gauge } from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid,
  Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis
} from "recharts";
import { numeric, asSingle, asRisk, type Offer, type Report } from "./types";

type Props = {
  offers: Offer[];
  demand: number;
  targetId: string;
  report: Report | null;
  onNavigate: () => void;
};

const axis = { fill: "#98a2b3", fontSize: 11 };
const tooltip = {
  background: "#ffffff",
  color: "#344054",
  border: "1px solid #e4e7ec",
  borderRadius: 12,
  boxShadow: "0 10px 36px rgba(16,24,40,.10)",
  fontSize: 12,
};

function Statistic({
  label, value, icon: Icon, detail, reportValue
}: {
  label: string; value: string; icon: typeof Activity; detail: string; reportValue?: string;
}) {
  return <div className="ta-stat-card">
    <div className="ta-stat-icon"><Icon size={22} strokeWidth={1.8}/></div>
    <div className="ta-stat-label">{label}</div>
    <div className="ta-stat-bottom">
      <strong>{value}</strong>
      {reportValue && <span className="ta-stat-badge">{reportValue}</span>}
    </div>
    <div className="ta-stat-detail">{detail}</div>
  </div>;
}

function CapacityGauge({ demand, total, unitCount }: { demand: number; total: number; unitCount: number }) {
  const coverage = total > 0 ? demand / total : 0;
  const pct = Math.round(coverage * 100);
  const shown = Math.min(100, Math.max(0, coverage * 100));
  const path = "M 27 133 A 93 93 0 0 1 213 133";
  return <div className="ta-capacity">
    <div className="ta-card-title">
      <div><h3>容量利用概览</h3><p>模拟总负荷与申报容量的比值</p></div>
      <span className="ta-card-icon"><Gauge size={19}/></span>
    </div>
    <div className="ta-gauge-wrap">
      <svg viewBox="0 0 240 150" aria-hidden="true">
        <path d={path} fill="none" stroke="#e9edf3" strokeWidth="16" strokeLinecap="round" pathLength={100} />
        <path className="ta-gauge-arc" d={path} fill="none" stroke="#465fff" strokeWidth="16" strokeLinecap="round"
          strokeDasharray={`${shown} 100`} pathLength={100} />
      </svg>
      <div className="ta-gauge-reading"><strong>{pct}%</strong><span>市场负荷 / 申报容量</span></div>
    </div>
    <div className="ta-gauge-explain">
      {coverage > 1 ? "总申报容量低于当前负荷，可能无法完全满足需求。" : "当前机组申报容量可以覆盖设置的市场负荷。"}
    </div>
    <div className="ta-capacity-footer">
      <div><span>市场负荷</span><strong>{numeric(demand)} MW</strong></div>
      <div><span>申报容量</span><strong>{numeric(total)} MW</strong></div>
      <div><span>参与机组</span><strong>{unitCount} 台</strong></div>
    </div>
  </div>;
}

export function DashboardOverview({ offers, demand, targetId, report, onNavigate }: Props) {
  const reducedMotion = useReducedMotion();
  const total = useMemo(() => offers.reduce((n, o) => n + o.quantity_mw, 0), [offers]);
  const ordered = useMemo(() => [...offers].sort((a,b) => a.bid_price - b.bid_price), [offers]);
  const cumulative = useMemo(() => {
    let capacity = 0;
    return ordered.map(o => {
      capacity += o.quantity_mw;
      return { name:o.unit_id, price:o.bid_price, capacity, quantity:o.quantity_mw };
    });
  }, [ordered]);
  const profit = report ? (report.mode === "risk" ? asRisk(report.best).expected_profit : asSingle(report.best).profit) : null;
  const percent = total === 0 ? 0 : Math.min(100, Math.round((demand / total) * 100));
  return <section className="ta-overview" aria-label="市场概览仪表盘">
    <div className="ta-top-dashboard">
      <div className="ta-dashboard-left">
        <div className="ta-stats-grid">
          <Statistic label="市场总负荷" value={numeric(demand) + " MW"} icon={Activity}
            detail="当前模拟场景的市场需求" reportValue="当前场景" />
          <Statistic label="总申报容量" value={numeric(total) + " MW"} icon={Boxes}
            detail={`${offers.length} 台机组参与，目标机组 ${targetId}`}
            reportValue={total < demand ? "容量不足" : "容量充足"}/>
        </div>
        <div className="ta-chart-card ta-bidding-chart">
          <div className="ta-card-title"><div><h3>机组报价分布</h3><p>当前各机组申报的报价，单位：价格/MWh</p></div>
            <span className="ta-card-tag"><BarChart3 size={15}/> 实际申报</span></div>
          <div className="ta-bars">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={offers} margin={{top:16,right:5,bottom:0,left:-21}} barSize={26}>
                <CartesianGrid stroke="#edf0f5" vertical={false}/>
                <XAxis dataKey="unit_id" tick={axis} axisLine={false} tickLine={false} tickMargin={12}/>
                <YAxis tick={axis} axisLine={false} tickLine={false} width={50}/>
                <Tooltip cursor={{fill:"#f2f4ff"}} contentStyle={tooltip}
                  formatter={(v, name) => [typeof v==="number"?numeric(v,2):v, name]}/>
                <Bar isAnimationActive={!reducedMotion} animationDuration={520} animationEasing="ease-out" dataKey="bid_price" name="机组报价" radius={[5,5,0,0]}>
                  {offers.map(o => <Cell key={o.unit_id} fill={o.unit_id===targetId ? "#465fff" : "#a6b4ff"}/>)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
      <CapacityGauge demand={demand} total={total} unitCount={offers.length}/>
    </div>
    <div className="ta-chart-card ta-wide-chart">
      <div className="ta-card-title"><div><h3>{report ? "策略分析已完成" : "市场供给与出清条件"}</h3>
        <p>{report ? "最新一次报价计算已生成真实结果，可进入报告查看。" : "按申报报价从低到高排列的累积供给量，基于当前机组数据计算。"}</p></div>
        <button className="ta-report-link" type="button" onClick={onNavigate}>
          {report ? "查看策略报告" : "打开机组分析"} <ArrowUpRight size={15}/>
        </button></div>
      {report ? <div className="ta-report-strip">
        <div><span>推荐报价</span><strong>{numeric(report.best.bid_price, 2)}</strong><small>价格 / MWh</small></div>
        <div><span>{report.mode==="risk" ? "期望利润" : "预计利润"}</span><strong>{numeric(profit ?? 0, 2)}</strong><small>当前结算周期</small></div>
        <div><span>试算报价</span><strong>{report.count}</strong><small>个候选</small></div>
        <div className="ta-report-complete"><Zap size={20}/><strong>计算完成</strong><span>详细分析报告已生成</span></div>
      </div> : <div className="ta-supply-chart">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={cumulative} margin={{top:16,right:22,bottom:0,left:-5}}>
            <defs><linearGradient id="taSupply" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#465fff" stopOpacity={.21}/>
              <stop offset="100%" stopColor="#465fff" stopOpacity={.01}/>
            </linearGradient></defs>
            <CartesianGrid stroke="#edf0f5" vertical={false}/>
            <XAxis dataKey="name" tick={axis} axisLine={false} tickLine={false} tickMargin={13}/>
            <YAxis tick={axis} axisLine={false} tickLine={false} width={55}/>
            <ReferenceLine y={demand} stroke="#e2a25a" strokeDasharray="5 5"
              label={{value:"市场负荷", position:"insideTopRight",fill:"#ba874b",fontSize:11}}/>
            <Tooltip contentStyle={tooltip} formatter={v => typeof v==="number" ? numeric(v,2) + " MW" : v}/>
            <Area isAnimationActive={!reducedMotion} animationDuration={620} animationEasing="ease-out" dataKey="capacity" name="累积供给容量" stroke="#465fff" strokeWidth={2.7} fill="url(#taSupply)"
              type="stepAfter" dot={{fill:"#465fff",r:3}} activeDot={{r:5}}/>
          </AreaChart>
        </ResponsiveContainer>
      </div>}
      <div className="ta-wide-foot"><span><TrendingUp size={14}/> 基于当前机组报价生成</span>
        <span>{report ? "查看报告以了解最优报价与利润" : `容量覆盖率 ${percent}% · 数据随参数编辑自动更新`}</span></div>
    </div>
  </section>;
}
