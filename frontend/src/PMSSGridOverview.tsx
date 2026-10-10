import { useMemo, useState } from "react";
import { Activity, GitBranch, Zap } from "lucide-react";
import { numeric, type PMSSInspection } from "./types";
import "./pmss-unified.css";

type Raw = Record<string, unknown>;
type Line = { lineId: string; fromBus: string; toBus: string; limitMw: number; reactancePu: number };
type UnitBid = { startPeriod: number; endPeriod: number;
  segmentDatas: {startPower: number; endPower: number; price: number; segmentOrder: number}[] };

function object(value: unknown): value is Raw {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}
function readGrid(snapshot: Raw) {
  const raw = snapshot.dcNetwork;
  if (!object(raw) || !Array.isArray(raw.buses) || !Array.isArray(raw.lines) ||
      !object(raw.unitBus) || !object(raw.hourlyDemandMw) ||
      raw.buses.length > 60 || raw.lines.length > 90) return null;
  const buses: string[] = raw.buses;
  if (!buses.length || !buses.every(bus => typeof bus === "string") ||
      new Set(buses).size !== buses.length) return null;
  const known = new Set(buses);
  const lines: Line[] = [];
  for (const entry of raw.lines) {
    if (!object(entry) || typeof entry.lineId !== "string" ||
        typeof entry.fromBus !== "string" || typeof entry.toBus !== "string" ||
        !known.has(entry.fromBus) || !known.has(entry.toBus) ||
        !finite(entry.limitMw) || entry.limitMw <= 0 ||
        !finite(entry.reactancePu) || entry.reactancePu <= 0) return null;
    lines.push(entry as Line);
  }
  const demand: Record<string, number[]> = {};
  for (const bus of buses) {
    const hourly = raw.hourlyDemandMw[bus];
    if (!Array.isArray(hourly) || hourly.length !== 24 ||
        !hourly.every(v => finite(v) && v >= 0)) return null;
    demand[bus] = hourly;
  }
  return {buses, lines, demand, unitBus: raw.unitBus};
}
function readHistoricalBid(snapshot: Raw, unitId: string, hour: number): UnitBid | null {
  const bids = snapshot.unitBids;
  if (!object(bids) || !object(bids[unitId]) || !Array.isArray(bids[unitId].datas)) return null;
  const entries = bids[unitId].datas as unknown[];
  const matches = entries.filter(e => object(e) && finite(e.startPeriod) &&
    finite(e.endPeriod) && e.startPeriod <= hour && e.endPeriod >= hour);
  if (matches.length !== 1 || !object(matches[0])) return null;
  const row = matches[0];
  if (!Array.isArray(row.segmentDatas) || row.segmentDatas.length > 5) return null;
  const segments = row.segmentDatas;
  if (!segments.every(s => object(s) && finite(s.startPower) &&
      finite(s.endPower) && finite(s.price) && finite(s.segmentOrder))) return null;
  return {startPeriod: row.startPeriod as number, endPeriod: row.endPeriod as number,
    segmentDatas: (segments as UnitBid["segmentDatas"]).slice().sort((a,b) => a.segmentOrder-b.segmentOrder)};
}

export function PMSSGridOverview({snapshot, inspection, target}: {
  snapshot: Raw; inspection: PMSSInspection; target: string;
}) {
  const [hour, setHour] = useState(1);
  const grid = useMemo(() => readGrid(snapshot), [snapshot]);
  const historicalBid = useMemo(() => readHistoricalBid(snapshot, target, hour), [snapshot, target, hour]);
  const attachedBus = grid?.unitBus[target];
  const [focusedBus, setFocusedBus] = useState("");
  const activeBus = focusedBus && grid?.buses.includes(focusedBus) ? focusedBus :
    typeof attachedBus === "string" ? attachedBus : "";
  const positions = useMemo(() => new Map(grid?.buses.map((bus,index) => {
    const angle = 2*Math.PI*index/(grid.buses.length || 1) - Math.PI/2;
    return [bus, {x:450 + 350*Math.cos(angle), y:215 + 168*Math.sin(angle)}] as const;
  }) ?? []), [grid]);
  const segmentMax = Math.max(1, ...(historicalBid?.segmentDatas.map(s=>s.endPower) ?? []));
  const priceMax = Math.max(1, ...(historicalBid?.segmentDatas.map(s=>s.price) ?? []));
  return <section className="pmss-unified-overview">
    <div className="pmss-panel">
      <div className="pmss-panel-head"><div>
        <small><GitBranch size={13}/> NETWORK / VERIFIED INPUT</small>
        <h3>电网拓扑与节点负荷</h3>
        <p>基于当前脱敏场景的母线、线路和机组接线。圆环为示意布局，不是物理地理位置。</p>
      </div><span className="pmss-state-label">{grid ? grid.buses.length+" 节点 / "+grid.lines.length+" 线路" : "无已核验拓扑"}</span></div>
      {grid ? <>
        <div className="pmss-grid-legend">
          <span><i className="pmss-legend-dot"/>普通节点</span>
          <span><i className="pmss-legend-dot chosen"/>机组 / 选中节点</span>
          <span><i className="pmss-legend-line"/>线路连接关系</span>
        </div>
        <div className="pmss-grid-canvas">
          <svg viewBox="0 0 900 440" role="img" aria-label={"包含"+grid.buses.length+"个节点及"+grid.lines.length+"条线路的非地理拓扑示意图"}>
            {grid.lines.map(line => {
              const a = positions.get(line.fromBus), b = positions.get(line.toBus);
              if (!a || !b) return null;
              const connected = activeBus && (line.fromBus===activeBus || line.toBus===activeBus);
              return <line key={line.lineId} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={connected?"var(--ta-primary)":"var(--ta-border)"} strokeOpacity={connected?0.95:0.8}
                strokeWidth={connected?2.8:1.5}><title>{line.lineId+" · "+line.fromBus+" → "+line.toBus+" · "+numeric(line.limitMw,1)+" MW"}</title></line>;
            })}
            {grid.buses.map(bus => {
              const pos=positions.get(bus)!;
              const selected = bus===activeBus;
              const hasUnit = Object.values(grid.unitBus).includes(bus);
              return <g key={bus} onClick={()=>setFocusedBus(bus)} tabIndex={0} role="button"
                aria-label={"查看节点 "+bus} onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();setFocusedBus(bus);}}}
                style={{cursor:"pointer"}}>
                <circle cx={pos.x} cy={pos.y} r={selected?13:hasUnit?10:8}
                  fill={selected?"var(--ta-primary)":hasUnit?"#049f78":"var(--ta-panel)"}
                  stroke={selected?"var(--ta-primary)":"var(--ta-muted)"} strokeWidth={selected?2:1.2}/>
                <text x={pos.x} y={pos.y-17} textAnchor="middle" fontSize={10}
                  fill="var(--ta-ink-2)">{bus}</text>
                <title>{bus+" · 第"+hour+"时段节点负荷 "+numeric(grid.demand[bus][hour-1],2)+" MW"}</title>
              </g>;
            })}
          </svg>
        </div>
        <div className="pmss-grid-footer">
          <label>检查时段
            <select value={hour} onChange={e=>setHour(Number(e.target.value))}>
              {Array.from({length:24},(_,i)=><option key={i+1} value={i+1}>{String(i+1).padStart(2,"0")} 时段</option>)}
            </select>
          </label>
          <div><span>选择节点</span><strong>{activeBus||"—"}</strong></div>
          <div><span>本时段节点负荷</span><strong>{activeBus?numeric(grid.demand[activeBus][hour-1],2)+" MW":"—"}</strong></div>
          <div><span>目标机组接入节点</span><strong>{typeof attachedBus==="string"?attachedBus:"未关联"}</strong></div>
        </div>
      </> : <p className="pmss-footnote">当前案例没有通过本地检查的完整 dcNetwork。不会使用随机节点或连线伪造真实电网。</p>}
    </div>
    <div className="pmss-panel">
      <div className="pmss-panel-head"><div><small><Zap size={13}/> MARKET / REFERENCE BID</small>
        <h3>市场规则与历史原始报价</h3>
        <p>与当前目标机组关联的历史申报，仅作参考，不是新方案，也不是提交入口。</p></div>
        <span className="pmss-state-label">只读</span>
      </div>
      <div className="pmss-rule-strip">
        <div><span>价格下限</span><strong>{inspection.historical_bid_rule_audit.price_floor??"未提供"}</strong></div>
        <div><span>价格上限</span><strong>{inspection.historical_bid_rule_audit.price_ceiling??"未提供"}</strong></div>
        <div><span>最多分段</span><strong>{inspection.max_segments}</strong></div>
        <div><span>案例日期</span><strong>{inspection.case_date||"未标注"}</strong></div>
      </div>
      <p className="pmss-bid-caption"><Activity size={14}/> {inspection.units.find(u=>u.unit_id===target)?.name||target} · 第 {hour} 时段 · 历史申报阶梯曲线</p>
      {historicalBid ? <>
        <svg className="pmss-bid-plot" viewBox="0 0 580 220" role="img" aria-label="所选机组的历史原始阶梯报价曲线">
          {Array.from({length:4},(_,i)=><line key={i} x1={46} x2={565} y1={25+45*i} y2={25+45*i}
            stroke="var(--ta-border)" strokeDasharray="4 6"/>)}
          <line x1="46" x2="565" y1="205" y2="205" stroke="var(--ta-muted)"/>
          <line x1="46" x2="46" y1="14" y2="205" stroke="var(--ta-muted)"/>
          {historicalBid.segmentDatas.map((segment,index)=>{
            const x1=46+(segment.startPower/segmentMax)*519;
            const x2=46+(segment.endPower/segmentMax)*519;
            const y=197-(segment.price/priceMax)*162;
            return <g key={index}><line x1={x1} x2={x2} y1={y} y2={y}
              stroke="var(--ta-primary)" strokeWidth={4} strokeLinecap="round"/>
              {index>0&&<line x1={x1} x2={x1} y1={197-(historicalBid.segmentDatas[index-1].price/priceMax)*162}
                y2={y} stroke="var(--ta-primary)" strokeWidth={2} strokeDasharray="3 3"/>}
              <title>{numeric(segment.startPower,1)+"–"+numeric(segment.endPower,1)+" MW / "+numeric(segment.price,2)}</title>
            </g>;
          })}
          <text x="46" y="218" fontSize="10" fill="var(--ta-muted)">0 MW</text>
          <text x="565" y="218" textAnchor="end" fontSize="10" fill="var(--ta-muted)">{numeric(segmentMax,0)} MW</text>
          <text x="48" y="13" fontSize="10" fill="var(--ta-muted)">历史申报价</text>
        </svg>
        <div className="pmss-table-scroll"><table className="pmss-table">
          <thead><tr><th>段</th><th>起始出力 (MW)</th><th>结束出力 (MW)</th><th>历史价格</th></tr></thead>
          <tbody>{historicalBid.segmentDatas.map((segment,index)=><tr key={index}>
            <td>{index+1}</td><td>{numeric(segment.startPower,2)}</td>
            <td>{numeric(segment.endPower,2)}</td><td>{numeric(segment.price,2)}</td>
          </tr>)}</tbody>
        </table></div>
      </> : <p className="pmss-footnote">当前目标机组或时段缺少可校验的原始报价段。</p>}
      <p className="pmss-footnote">历史报价可能按当时规则保存，不代表当前可合法提交；出清结果需以有来源的历史数据为准。这里不执行 PMSS SCUC/SCED。</p>
    </div>
  </section>;
}
