import smirelLogo from "./assets/smirel-logo.png";
import { useEffect, useState, type ReactNode, type CSSProperties } from "react";
import { ArrowDown, ArrowRight, ArrowUpRight, Activity, BarChart3, Check, ChevronRight, CircleDot, Compass, Gauge, Layers3, Menu, MousePointer2, MoveUpRight, ShieldCheck, SlidersHorizontal, Sparkles, X } from "lucide-react";
import "./landing.css";
import "./landing-dark.css";
import "./portal-polish.css";
import "./landing-buttons.css";
import PowerConstellation from "./PowerConstellation";

type LandingProps = { workspaceHref: string };
const flowSteps = [
  { id: "01", name: "感知市场", en: "OBSERVE", note: "从市场与机组数据开始，建立决策坐标。" },
  { id: "02", name: "构建报价", en: "MODEL", note: "让每一组报价方案都拥有可解释的依据。" },
  { id: "03", name: "模拟出清", en: "SIMULATE", note: "把不确定的市场反应转化为可分析的情景。" },
  { id: "04", name: "评估收益", en: "REFINE", note: "对比结果、理解风险，继续改进策略。" },
];

function Brand({ inverse = false }: { inverse?: boolean }) {
  return <span className={"pb-brand" + (inverse ? " pb-brand-inverse" : "")}>
    <img className="pb-brand-smirel" src={smirelLogo} alt="Smirel" width={92} height={30} />
    <span className="pb-brand-word">PowerBid</span>
  </span>;
}

function SectionTag({ children, dark = false }: { children: ReactNode; dark?: boolean }) {
  return <span className={"pb-section-tag" + (dark ? " pb-section-tag-dark" : "")}><span className="pb-small-cross">✳</span>{children}</span>;
}
function CurveGraphic({ variant = "purple" }: { variant?: "purple" | "blue" }) {
  return <svg viewBox="0 0 380 200" className={"pb-curve-graphic pb-curve-" + variant} role="img" aria-label="报价与市场出清趋势示意图">
    <defs><linearGradient id={"pb-curve-fill-" + variant} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={variant === "purple" ? "#9e91ff" : "#5a9df6"} stopOpacity=".32"/><stop offset="1" stopColor={variant === "purple" ? "#9e91ff" : "#5a9df6"} stopOpacity="0"/></linearGradient></defs>
    {[35,80,125,170].map(y=><line key={y} x1="0" x2="380" y1={y} y2={y} stroke="currentColor" strokeOpacity=".11" strokeDasharray="3 5"/>)}
    <path d="M0 160 C42 154 53 101 101 122 S166 180 215 92 S298 94 380 26 L380 200 L0 200Z" fill={"url(#pb-curve-fill-" + variant + ")"}/>
    <path d="M0 160 C42 154 53 101 101 122 S166 180 215 92 S298 94 380 26" fill="none" stroke={variant === "purple" ? "#7869f5" : "#3a80f4"} strokeWidth="3" strokeLinecap="round"/>
    <path d="M0 118 C35 127 83 106 128 110 S224 64 268 73 S337 65 380 55" fill="none" stroke="#a9b7cd" strokeWidth="1.6" strokeDasharray="5 5"/>
    <circle cx="215" cy="92" r="5" fill="#fff" stroke="#7869f5" strokeWidth="2.5"/>
  </svg>;
}
function NetworkGraphic() {
  const nodes = [[88,140],[210,64],[270,232],[410,124],[530,40],[592,213],[760,90],[854,238],[976,126],[1100,44],[1146,215]] as const;
  const links = [[0,1],[0,2],[1,3],[1,4],[2,3],[2,5],[3,4],[3,5],[3,6],[4,6],[5,7],[6,7],[6,8],[7,8],[8,9],[8,10],[9,10]] as const;
  return <svg viewBox="0 0 1220 290" preserveAspectRatio="xMidYMid meet" className="pb-network-graphic" role="img" aria-label="电力网络节点与连接线的动态示意">
    <defs><linearGradient id="pb-network-link"><stop stopColor="#6574ff" stopOpacity=".12"/><stop offset=".53" stopColor="#91a1ff" stopOpacity=".8"/><stop offset="1" stopColor="#687dfa" stopOpacity=".2"/></linearGradient></defs>
    {links.map(([a,b],i)=><line key={i} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]} stroke="url(#pb-network-link)" strokeWidth="1.2" />)}
    {links.filter((_,i)=>i%3===0).map(([a,b],i)=><line key={"pulse"+i} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]} className="pb-network-pulse" style={{ animationDelay: String(i * -.7) + "s" }}/>)}
    {nodes.map(([x,y],i)=><g key={i}><circle cx={x} cy={y} r={i%4===0?17:11} fill="#6776f6" opacity=".08"/><circle cx={x} cy={y} r={i%4===0?5.1:3.5} fill="#aeb9ff"/><circle cx={x} cy={y} r="1.8" fill="white"/></g>)}
  </svg>;
}

export default function LandingPage({ workspaceHref }: LandingProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [bid, setBid] = useState(310);
  const [scrolled, setScrolled] = useState(false);
  const [activeStep, setActiveStep] = useState(1);
  useEffect(() => {
    const oldTitle = document.title;
    document.title = "PowerBid Lab — 电力报价系统小组作业";
    const desc = document.querySelector('meta[name="description"]');
    const oldDesc = desc?.getAttribute("content");
    desc?.setAttribute("content", "PowerBid Lab — 面向电力市场教学与研究的报价决策实验室。探索市场、策略、出清与风险之间的联系。");
    const scroll = () => setScrolled(window.scrollY > 22);
    window.addEventListener("scroll", scroll, { passive: true });
    scroll();
    const revealElements = document.querySelectorAll(".pb-reveal");
    const observer = new IntersectionObserver(items => {
      items.forEach(item => { if (item.isIntersecting) { item.target.classList.add("pb-visible"); observer.unobserve(item.target); } });
    }, { threshold: .12, rootMargin: "0px 0px -24px 0px" });
    revealElements.forEach(el => observer.observe(el));
    return () => {
      document.title = oldTitle;
      if (oldDesc !== null && oldDesc !== undefined) desc?.setAttribute("content", oldDesc);
      window.removeEventListener("scroll", scroll);
      observer.disconnect();
    };
  }, []);
  const bidPosition = ((bid - 180) / 220) * 100;
  return <div className="pb-landing" id="top">
    <header className={"pb-site-header" + (scrolled ? " pb-header-scrolled" : "")}>
      <div className="pb-header-inner">
        <a href="#top" className="pb-logo-link" aria-label="PowerBid Lab 返回首页"><Brand /></a>
        <nav className={"pb-header-links" + (menuOpen ? " pb-menu-open" : "")} aria-label="网站导航">
          <a href="#philosophy" onClick={()=>setMenuOpen(false)}>设计理念</a>
          <a href="#capabilities" onClick={()=>setMenuOpen(false)}>核心能力</a>
          <a href="#explore" onClick={()=>setMenuOpen(false)}>交互探索</a>
          <a href="#workflow" onClick={()=>setMenuOpen(false)}>研究流程</a>
          <a className="pb-mobile-auth-entry" href={import.meta.env.BASE_URL + "login"} onClick={()=>setMenuOpen(false)}>登录账号 <ArrowUpRight size={15}/></a>
          <a className="pb-mobile-auth-entry" href={import.meta.env.BASE_URL + "register"} onClick={()=>setMenuOpen(false)}>注册账号 <ArrowUpRight size={15}/></a>
          <a className="pb-mobile-enter" href={workspaceHref} onClick={()=>setMenuOpen(false)}>进入工作台 <ArrowUpRight size={16}/></a>
        </nav>
        <div className="pb-header-actions">
          <a href={import.meta.env.BASE_URL + "login"} className="pb-header-auth-link">登录</a>
          <a href={import.meta.env.BASE_URL + "register"} className="pb-header-auth-register">注册</a>
          <a href={workspaceHref} className="pb-header-cta">进入工作台 <ArrowUpRight size={16}/></a>
        </div>
        <a className="pb-mobile-auth-quick" href={import.meta.env.BASE_URL + "login"}>登录</a>
        <button className="pb-menu-toggle" type="button" onClick={()=>setMenuOpen(v=>!v)} aria-label={menuOpen?"关闭导航":"打开导航"} aria-expanded={menuOpen}>{menuOpen?<X size={21}/>:<Menu size={21}/>}</button>
      </div>
    </header>
    <main>
      <section className="pb-hero" aria-labelledby="pb-hero-title">
        <div className="pb-hero-grid" aria-hidden="true"/>
        <div className="pb-hero-orb" aria-hidden="true">
          <PowerConstellation/>
        </div>
        <div className="pb-container pb-hero-inner">
          {/* Keep HUDs anchored to the safe hero content area, not the decorative orb. */}
          <div className="pb-hero-hud pb-hero-hud-top" aria-hidden="true"><span className="pb-hero-hud-label"><i/> NETWORK / VISUAL</span><strong>电网潮流 · 可视化</strong><small>拓扑与能量轨迹示意</small></div>
          <div className="pb-hero-hud pb-hero-hud-bottom" aria-hidden="true"><span className="pb-hero-hud-label"><i/> STRATEGY / LAB</span><strong>报价决策空间</strong><small>从市场数据到情景分析</small></div>
          <div className="pb-hero-copy">
            <div className="pb-hero-eyebrow"><span className="pb-eyebrow-line"/>POWER MARKET INTELLIGENCE<span className="pb-eyebrow-number">© 2026</span></div>
            <h1 id="pb-hero-title">电力报价系统<br/><em>小组作业</em></h1>
            <p className="pb-hero-subtitle">从每一度电的流动，到每一次报价的选择。<br/>探索电力市场复杂系统背后，更清晰的决策路径。</p>
            <div className="pb-hero-actions"><a className="pb-button-main" href={workspaceHref}>开启决策实验室 <span><ArrowUpRight size={21}/></span></a><a className="pb-text-link" href="#philosophy">探索设计 <ArrowDown size={16}/></a></div>
            <div className="pb-hero-proof" aria-label="系统研究方向">
              <div className="pb-hero-proof-item"><strong>24H</strong><span>多时段研究</span></div>
              <div className="pb-hero-proof-item"><strong>5 段</strong><span>报价方案探索</span></div>
              <div className="pb-hero-proof-item"><strong>PMSS</strong><span>市场仿真研究</span></div>
            </div>
          </div>
          <div className="pb-hero-bottom"><span><span className="pb-hero-cross">✳</span> A DIFFERENT PERSPECTIVE ON ENERGY</span><a href="#philosophy">SCROLL TO DISCOVER <ArrowDown size={15}/></a><span>01 / 05</span></div>
        </div>
      </section>

      <div className="pb-signal-ribbon" aria-label="研究工作流">
        <div><span>01 / DATA</span><strong>研究市场数据</strong><small>从机组、价格与负荷开始</small></div>
        <div><span>02 / DECISION</span><strong>构建报价策略</strong><small>比较候选报价与约束</small></div>
        <div><span>03 / INSIGHT</span><strong>评估决策表现</strong><small>审视收益、风险与出清</small></div>
      </div>

      <section className="pb-intro pb-section" id="philosophy">
        <div className="pb-container">
          <div className="pb-intro-top pb-reveal"><SectionTag>THE PHILOSOPHY / 设计理念</SectionTag><span className="pb-section-index">[ 001 — 005 ]</span></div>
          <div className="pb-intro-layout">
            <h2 className="pb-display-text pb-reveal">复杂的市场，<br/>值得一种<span>更清晰</span><br/>的理解方式。</h2>
            <div className="pb-intro-aside pb-reveal"><div className="pb-intro-mark"><CircleDot size={35} strokeWidth={1.1}/></div><p>电力市场由无数相互影响的选择构成。我们把数据、模型与市场出清放在同一张画布上，让抽象的经济与物理关系变得可见、可探索、可验证。</p><div className="pb-intro-line"><span>RESEARCH. SIMULATE. UNDERSTAND.</span><MoveUpRight size={17}/></div></div>
          </div>
          <div className="pb-micro-rule"><span>CLARITY IS AN ADVANTAGE</span><span>↓</span></div>
        </div>
      </section>

      <section className="pb-capabilities pb-section" id="capabilities">
        <div className="pb-container">
          <div className="pb-section-head pb-reveal"><div><SectionTag>MADE FOR DECISIONS / 核心能力</SectionTag><h2>由数据出发，<br/><span>向更好的决策靠近。</span></h2></div><p>不仅展示数字，更让每一个结果<br/>都可以被理解、比较和追溯。</p></div>
          <div className="pb-feature-grid">
            <article className="pb-feature pb-feature-main pb-reveal">
              <div className="pb-feature-top"><span>01 / STRATEGY LAB</span><span className="pb-feature-icon"><SlidersHorizontal size={19}/></span></div>
              <div className="pb-feature-visual"><div className="pb-visual-meta"><span>STRATEGY SIGNAL</span><span>SIMULATED VIEW</span></div><CurveGraphic/></div>
              <div className="pb-feature-bottom"><h3>让报价策略，有迹可循。</h3><p>从机组申报到候选策略试算，直观理解价格、出清结果与收益之间的联系。</p></div>
            </article>
            <article className="pb-feature pb-feature-side pb-reveal">
              <div className="pb-feature-top"><span>02 / RISK LANDSCAPE</span><span className="pb-feature-icon"><Gauge size={19}/></span></div>
              <div className="pb-risk-visual"><div className="pb-risk-halo"><div className="pb-risk-center"><span>SCENARIOS</span><strong>09</strong><small>示意情景数量</small></div></div><div className="pb-risk-dots"><span/><span/><span/><span/><span/></div></div>
              <div className="pb-feature-bottom"><h3>让不确定性，变得可读。</h3><p>比较不同负荷、竞争报价与风险情景下的策略表现。</p></div>
            </article>
            <article className="pb-feature pb-feature-wide pb-reveal">
              <div className="pb-wide-icon"><Layers3 size={24} strokeWidth={1.5}/></div>
              <div className="pb-wide-copy"><span>03 / MARKET & NETWORK</span><h3>连接市场逻辑与电网约束。</h3><p>以市场模拟、网络分析和 PMSS 研究流程，观察报价决策如何影响出清结果。</p></div>
              <div className="pb-wide-orbit" aria-hidden="true"><span/><span/><span/><span/></div>
              <ArrowUpRight className="pb-wide-arrow" size={26} strokeWidth={1.3}/>
            </article>
          </div>
        </div>
      </section>

      <section className="pb-explore pb-section" id="explore">
        <div className="pb-container">
          <div className="pb-section-head pb-reveal"><div><SectionTag>INTERACTIVE STUDY / 交互探索</SectionTag><h2>改变一个变量。<br/><span>观察另一种可能。</span></h2></div><p>与市场模型之间的距离，<br/>可以只剩下一次拖动。</p></div>
          <div className="pb-lab-panel pb-reveal">
            <div className="pb-lab-header"><div className="pb-lab-indicator"><span/><span/><span/></div><span>POWERBID / INTERACTIVE STUDY</span><span className="pb-lab-badge"><Sparkles size={12}/> INTERACTIVE DEMO</span></div>
            <div className="pb-lab-body">
              <div className="pb-lab-controls"><div className="pb-lab-control-heading"><span>EXPERIMENT 001</span><span className="pb-lab-live"><i/>LIVE PREVIEW</span></div><h3>报价探索器<span>.</span></h3><p>拖动报价滑块，观察曲线如何变化。<br/>这是首页的交互示意，不是实际优化结果。</p><label htmlFor="pb-bid-slider">候选报价 <span>PRICE / MWh</span></label><div className="pb-lab-value">{bid}<small>元 / MWh</small></div><input id="pb-bid-slider" type="range" min="180" max="400" step="10" value={bid} onChange={e=>setBid(Number(e.target.value))} style={{"--pb-range-value":String(bidPosition)+"%"} as CSSProperties}/><div className="pb-slider-scale"><span>180</span><span>290</span><span>400</span></div><div className="pb-lab-hint"><MousePointer2 size={14}/> 拖动滑块，实时观察右侧示意图</div></div>
              <div className="pb-lab-chart"><div className="pb-lab-chart-head"><div><span>ILLUSTRATIVE SIGNAL</span><strong>报价变化趋势</strong></div><span className="pb-lab-chart-type"><Activity size={15}/> TREND VIEW</span></div><svg viewBox="0 0 560 286" className="pb-interactive-chart" preserveAspectRatio="none" role="img" aria-label="示意图：随着候选报价改变，曲线上的选择点同步移动">
                <defs><linearGradient id="pb-demo-gradient" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#7f8efb" stopOpacity=".23"/><stop offset="1" stopColor="#7f8efb" stopOpacity="0"/></linearGradient></defs>
                {[40,96,152,208,264].map(y=><line key={y} x1="20" x2="540" y1={y} y2={y} className="pb-chart-gridline"/>)}
                <path d="M20 244 C80 232 118 180 174 174 S276 211 332 128 S438 86 540 38 L540 274 L20 274 Z" fill="url(#pb-demo-gradient)"/>
                <path d="M20 244 C80 232 118 180 174 174 S276 211 332 128 S438 86 540 38" fill="none" stroke="#7b83f3" strokeWidth="3.2" strokeLinecap="round"/>
                <line x1={20 + bidPosition * 5.2} x2={20 + bidPosition * 5.2} y1="26" y2="274" stroke="#5265ef" strokeDasharray="5 6" strokeWidth="1.2"/>
                <circle cx={20 + bidPosition * 5.2} cy={244 - bidPosition * 1.88 + 20 * Math.sin(bidPosition / 8)} r="7" fill="#fff" stroke="#5265ef" strokeWidth="3"/>
              </svg><div className="pb-lab-chart-foot"><span>180</span><span>候选价格 / 示意</span><span>400</span></div></div>
            </div>
            <div className="pb-lab-footer"><span><CircleDot size={14}/> 教学与研究环境 · 示意图形不代表实时电力交易</span><a href={workspaceHref}>在真实工作台中试算 <ArrowUpRight size={17}/></a></div>
          </div>
        </div>
      </section>

      <section className="pb-flow pb-section" id="workflow">
        <div className="pb-container">
          <div className="pb-flow-header pb-reveal"><div><SectionTag dark>AN INTELLIGENT FLOW / 研究流程</SectionTag><h2>让每一次探索，<br/><em>都通向下一次发现。</em></h2></div><span className="pb-flow-annotation">EVERY DECISION<br/>HAS A TRACE.</span></div>
          <div className="pb-flow-network pb-reveal"><NetworkGraphic/><span className="pb-network-label">A CONNECTED SYSTEM OF DECISIONS</span></div>
          <div className="pb-flow-steps">{flowSteps.map((step,i)=><button key={step.id} type="button" className={"pb-flow-step pb-reveal" + (activeStep===i?" pb-flow-active":"")} onClick={()=>setActiveStep(i)} aria-pressed={activeStep===i}><span className="pb-flow-step-top"><span>{step.id} / {step.en}</span><ChevronRight size={17}/></span><strong>{step.name}</strong><span className="pb-flow-step-note">{step.note}</span></button>)}</div>
          <div className="pb-flow-bottom"><span>FROM INFORMATION TO INSIGHT</span><span>POWERBID LAB © 2026</span></div>
        </div>
      </section>

      <section className="pb-product pb-section" id="product">
        <div className="pb-container">
          <div className="pb-section-head pb-reveal"><div><SectionTag>THE WORKSPACE / 产品界面</SectionTag><h2>艺术之外，<br/><span>是严谨的决策工具。</span></h2></div><p>真正可操作的工作台。<br/>用模型与结果，而不是装饰，支持每一次研究。</p></div>
          <div className="pb-browser pb-reveal">
            <div className="pb-browser-top"><div className="pb-browser-dots"><span/><span/><span/></div><div className="pb-browser-address"><span className="pb-address-lock">⌁</span> powerbid / workspace</div><div className="pb-browser-button"><span/> RESEARCH MODE</div></div>
            <div className="pb-browser-content">
              <aside className="pb-browser-sidebar"><Brand/><div className="pb-browser-sidebar-rule"/><span className="pb-browser-navitem pb-browser-nav-active"><span className="pb-nav-square"/>决策工作台</span><span className="pb-browser-navitem"><Layers3 size={14}/>机组申报数据</span><span className="pb-browser-navitem"><BarChart3 size={14}/>策略分析</span><span className="pb-browser-navitem"><Gauge size={14}/>压力情景</span><span className="pb-browser-navitem"><ShieldCheck size={14}/>试算明细</span></aside>
              <div className="pb-browser-workspace"><div className="pb-browser-crumb">WORKSPACE <ChevronRight size={11}/> STRATEGY OVERVIEW</div><div className="pb-browser-title"><div><h3>报价策略工作台</h3><span>在同一空间，理解市场与策略的关联</span></div><div className="pb-browser-run">运行报价分析 <ArrowRight size={13}/></div></div><div className="pb-browser-kpis"><div><small>市场总负荷</small><strong>700 <em>MW</em></strong><span>DEMO SCENARIO</span></div><div><small>总申报容量</small><strong>1,300 <em>MW</em></strong><span>4 GENERATORS</span></div><div><small>容量覆盖率</small><strong>54 <em>%</em></strong><span>SIMULATED DATA</span></div></div><div className="pb-browser-chart-panel"><div className="pb-browser-panel-title"><span>机组报价与市场趋势</span><span>MARKET OVERVIEW</span></div><CurveGraphic variant="blue"/><div className="pb-browser-axis"><span>G1</span><span>G2</span><span>G3</span><span>G4</span></div></div></div>
            </div>
          </div>
          <div className="pb-product-bottom pb-reveal"><div><span className="pb-product-check"><Check size={15}/></span>现有报价工作台与 PMSS 研究功能保持独立</div><a className="pb-product-link" href={workspaceHref}>进入完整工作台 <ArrowUpRight size={19}/></a></div>
        </div>
      </section>

      <section className="pb-finale" id="enter">
        <div className="pb-finale-halo" aria-hidden="true"/><div className="pb-container pb-finale-inner"><div className="pb-finale-top"><SectionTag dark>THE NEXT DECISION IS YOURS</SectionTag><Compass size={32} strokeWidth={1}/></div><h2 className="pb-reveal">探索下一种<br/><em>可能性<span>.</span></em></h2><div className="pb-finale-bottom"><p>PowerBid Lab<br/>让电力市场研究，拥有更直观的语言。</p><a href={workspaceHref}>开启工作台 <ArrowUpRight size={25}/></a></div></div>
      </section>
    </main>
    <footer className="pb-footer"><div className="pb-container pb-footer-inner"><Brand/><span>POWER MARKET RESEARCH · TEACHING & SIMULATION ONLY</span><a href="#top">返回顶部 ↑</a><span>© 2026 POWERBID LAB</span></div></footer>
  </div>;
}
