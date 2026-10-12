import { useEffect, useRef, useState } from "react";
import {
  Activity, ArrowUpRight, BarChart3, ChevronRight, ChartNoAxesCombined,
  Database, Expand, Gauge, Layers3, Network, ShieldCheck, X
} from "lucide-react";
import "./landing-workspace-cards.css";

type CardKind = "strategy" | "risk" | "network";

const previewMeta: Record<CardKind,{heading:string;subtitle:string;nav:string;code:string}> = {
  strategy: {
    heading: "智能报价策略", subtitle: "五段申报与候选策略对比",
    nav: "策略分析", code: "STRATEGY / DEMO"
  },
  risk: {
    heading: "风险评估中心", subtitle: "识别约束与验证边界",
    nav: "风险评估", code: "RISK / DEMO"
  },
  network: {
    heading: "电网与出清研究", subtitle: "拓扑、约束与出清数据",
    nav: "网络分析", code: "NETWORK / DEMO"
  }
};

function BidCurvePreview() {
  const levels = [[36,164],[104,138],[168,110],[230,77],[296,43]] as const;
  return <div className="pb-w-chart" aria-hidden="true">
    <div className="pb-w-panel-label"><span>报价曲线 / 示例</span><span>5 SEGMENTS</span></div>
    <svg viewBox="0 0 332 190" preserveAspectRatio="xMidYMid meet">
      {[42,87,132,174].map(y=><line key={y} x1="19" x2="319" y1={y} y2={y} className="pb-w-gridline"/>)}
      <path d="M19 164 H66 V138 H126 V110 H186 V77 H250 V43 H316" className="pb-w-stairline"/>
      {levels.map(([x,y],i)=><circle key={i} cx={x} cy={y} r="3.2" className="pb-w-plot-dot"/>)}
      <text x="19" y="185">0</text><text x="278" y="185">申报容量 →</text>
    </svg>
    <div className="pb-w-chart-bottom"><span>仅为五段报价形式示意</span><span>PRICE / MWh</span></div>
  </div>;
}

function RiskPreview() {
  return <div className="pb-w-risk" aria-label="风险分析功能示意">
    <div className="pb-w-panel-label"><span>验证项目</span><span>RESEARCH VIEW</span></div>
    <div className="pb-w-risk-checks">
      <div><span className="pb-w-risk-symbol"><ShieldCheck size={14}/></span><span><strong>成本与申报边界</strong><small>报价及机组参数检查</small></span><i/></div>
      <div><span className="pb-w-risk-symbol"><Network size={14}/></span><span><strong>网络物理约束</strong><small>验证所需模型参数</small></span><i/></div>
      <div><span className="pb-w-risk-symbol"><Activity size={14}/></span><span><strong>历史案例一致性</strong><small>区分模拟与真实出清</small></span><i/></div>
    </div>
    <div className="pb-w-chart-bottom"><span>只有完成验证才能给出推荐</span><span>POLICY</span></div>
  </div>;
}

function TopologyPreview() {
  const points: ReadonlyArray<readonly [number,number]> = [
    [44,112],[100,54],[115,155],[166,104],[217,52],[240,139],[294,90],[296,157],[169,174]
  ];
  const links: ReadonlyArray<readonly [number,number]> = [[0,1],[0,2],[0,3],[1,3],[1,4],[2,3],[2,8],[3,4],[3,5],[3,8],[4,6],[5,6],[5,7],[6,7],[7,8]];
  return <div className="pb-w-topology" aria-hidden="true">
    <div className="pb-w-panel-label"><span>电网拓扑 / 示意</span><span>DC MODEL / DEMO</span></div>
    <svg viewBox="0 0 332 198" preserveAspectRatio="xMidYMid meet">
      {links.map(([a,b],i)=><line key={i} x1={points[a][0]} y1={points[a][1]} x2={points[b][0]} y2={points[b][1]} className="pb-w-topology-link"/>)}
      {points.map(([x,y],i)=><g key={i}><circle cx={x} cy={y} r="8" className="pb-w-topology-glow"/><circle cx={x} cy={y} r={i%3===0?3.6:2.7} className="pb-w-topology-node"/></g>)}
    </svg>
    <div className="pb-w-chart-bottom"><span>示意网络 · 非 PMSS 真实结果</span><span>GRID</span></div>
  </div>;
}

function PreviewWindow({kind}:{kind:CardKind}) {
  const info=previewMeta[kind];
  return <div className={"pb-w-window pb-w-window-"+kind}>
    <div className="pb-w-titlebar">
      <div className="pb-w-traffic" aria-hidden="true"><i/><i/><i/></div>
      <div className="pb-w-title">PowerBid Studio <span>/</span> Workspace</div>
      <div className="pb-w-title-meta">PREVIEW</div>
    </div>
    <div className="pb-w-layout">
      <aside className="pb-w-sidebar" aria-label="预览侧边栏">
        <div className="pb-w-side-brand"><span className="pb-w-brand-mark"><Layers3 size={14}/></span> PowerBid</div>
        <div className="pb-w-sidebar-label">WORKSPACE</div>
        <div className={"pb-w-side-link"+(kind==="strategy"?" is-active":"")}><ChartNoAxesCombined size={13}/> 策略分析</div>
        <div className={"pb-w-side-link"+(kind==="risk"?" is-active":"")}><ShieldCheck size={13}/> 风险评估</div>
        <div className={"pb-w-side-link"+(kind==="network"?" is-active":"")}><Network size={13}/> 网络分析</div>
        <div className="pb-w-side-link"><Database size={13}/> 市场数据</div>
        <div className="pb-w-sidebar-spacer"/>
        <div className="pb-w-sidebar-foot"><span className="pb-w-online-dot"/>教学研究环境</div>
      </aside>
      <div className="pb-w-main">
        <div className="pb-w-breadcrumb">RESEARCH <ChevronRight size={11}/> {info.code}</div>
        <div className="pb-w-main-header">
          <div><h4>{info.heading}</h4><p>{info.subtitle}</p></div>
          <div className="pb-w-demo-chip">演示界面</div>
        </div>
        <div className="pb-w-kpi-row">
          <div><span>{kind==="strategy"?"申报形式":kind==="risk"?"风险维度":"研究模型"}</span><strong>{kind==="strategy"?"五段报价":kind==="risk"?"多项约束":"DC 网络"}</strong></div>
          <div><span>{kind==="strategy"?"优化范围":kind==="risk"?"校验阶段":"案例来源"}</span><strong>{kind==="strategy"?"24h 研究":kind==="risk"?"待验证":"教学案例"}</strong></div>
          <div><span>数据状态</span><strong className="pb-w-neutral">示意数据</strong></div>
        </div>
        {kind==="strategy"?<BidCurvePreview/>:kind==="risk"?<RiskPreview/>:<TopologyPreview/>}
      </div>
    </div>
  </div>;
}

/** A faithful layout pattern, not Alma's product imagery. The preview is non-live. */
export default function WorkspacePreviewCard({kind}:{kind:CardKind}) {
  const [expanded,setExpanded]=useState(false);
  const closeRef=useRef<HTMLButtonElement>(null);
  const launchRef=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    if (!expanded) return;
    const former=document.body.style.overflow;
    document.body.style.overflow="hidden";
    closeRef.current?.focus();
    const onKey=(event:KeyboardEvent)=>{
      if(event.key==="Escape") setExpanded(false);
      if(event.key==="Tab") {
        event.preventDefault();
        closeRef.current?.focus();
      }
    };
    document.addEventListener("keydown",onKey);
    return ()=>{
      document.body.style.overflow=former;
      document.removeEventListener("keydown",onKey);
      launchRef.current?.focus();
    };
  },[expanded]);
  return <>
    <button ref={launchRef} className="pb-w-preview-trigger" type="button" onClick={()=>setExpanded(true)}
      aria-label={"放大查看"+previewMeta[kind].heading+"的工作台界面示意"}>
      <PreviewWindow kind={kind}/>
      <span className="pb-w-expand-cue"><Expand size={13}/> 点击查看</span>
    </button>
    {expanded && <div className="pb-w-lightbox" onMouseDown={e=>{if(e.target===e.currentTarget)setExpanded(false);}}>
      <div className="pb-w-lightbox-panel" role="dialog" aria-modal="true" aria-label={previewMeta[kind].heading+" · 工作台界面示意"}>
        <button ref={closeRef} type="button" className="pb-w-lightbox-close" aria-label="关闭放大预览" onClick={()=>setExpanded(false)}><X size={19}/></button>
        <PreviewWindow kind={kind}/>
        <div className="pb-w-lightbox-caption"><span>PowerBid Studio · 界面设计预览 / 非实时数据</span><span>ESC 关闭 <ArrowUpRight size={12}/></span></div>
      </div>
    </div>}
  </>;
}
