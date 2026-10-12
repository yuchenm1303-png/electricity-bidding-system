import smirelLogo from "./assets/smirel-logo.png";
import { lazy, Suspense, useEffect, useState, type CSSProperties } from "react";
import { ArrowDown, ArrowRight, ArrowUpRight, ChevronRight, Menu, Minus, Plus, RotateCcw, X } from "lucide-react";
// The public homepage owns one scoped design sheet. The shared liquid-glass
// renderer keeps its original independently loaded style bundle.
import "./landing-minimal.css";
import PowerConstellation from "./PowerConstellation";

const PublicLiquidGlass = lazy(() => import("./PublicLiquidGlass"));

type LandingProps = { workspaceHref: string };
const sections = [
  { id: "philosophy", name: "设计理念" },
  { id: "capabilities", name: "核心能力" },
  { id: "explore", name: "交互探索" },
  { id: "workflow", name: "研究流程" },
] as const;

const steps = [
  { code: "01", label: "感知市场", en: "OBSERVE", detail: "整理机组参数、负荷与市场规则，明确策略适用的案例边界。" },
  { code: "02", label: "构建报价", en: "MODEL", detail: "生成并比较合规的五段报价方案，记录成本、网络与风险约束。" },
  { code: "03", label: "模拟出清", en: "SIMULATE", detail: "区分本地模型仿真与老师 PMSS 原版出清，避免混淆验证结果。" },
  { code: "04", label: "评估复盘", en: "REVIEW", detail: "对照出清和预测差异，追溯风险原因并调整后续策略。" },
] as const;

const demoCurveSegments = [
  [[20,244],[80,232],[118,180],[174,174]],
  [[174,174],[230,168],[276,211],[332,128]],
  [[332,128],[388,45],[438,86],[540,38]],
] as const;

function pointOnDemoCurve(percent: number) {
  const x = 20 + Math.max(0, Math.min(100, percent)) * 5.2;
  const segment = x <= 174 ? demoCurveSegments[0] : x <= 332 ? demoCurveSegments[1] : demoCurveSegments[2];
  const cubic = (a: number,b: number,c: number,d: number,t: number) =>
    (1-t)**3*a + 3*(1-t)**2*t*b + 3*(1-t)*t*t*c + t**3*d;
  let lo = 0,hi = 1;
  for (let i=0;i<22;i++) {
    const mid=(lo+hi)/2;
    if (cubic(segment[0][0],segment[1][0],segment[2][0],segment[3][0],mid)<x) lo=mid;
    else hi=mid;
  }
  const t=(lo+hi)/2;
  return {x,y:cubic(segment[0][1],segment[1][1],segment[2][1],segment[3][1],t)};
}

function Brand() {
  return <span className="pb-brand">
    <img className="pb-brand-smirel" src={smirelLogo} width={92} height={30} alt="Smirel"/>
    <span className="pb-brand-word">PowerBid</span>
  </span>;
}

function StrategySketch() {
  return <div className="pb-e-sketch pb-e-sketch-chart" aria-hidden="true">
    <span className="pb-e-sketch-eyebrow">STRATEGY / BID CURVE</span>
    <svg viewBox="0 0 480 240" preserveAspectRatio="xMidYMid meet" className="pb-e-preview-curve">
      {[55,115,175,220].map(y=><line key={y} x1="12" x2="468" y1={y} y2={y} className="pb-e-gridline"/>)}
      <path d="M12 200 C92 194 116 143 174 152 S263 181 315 107 S407 79 468 40" className="pb-e-line-secondary"/>
      <path d="M12 219 L72 219 L72 175 L164 175 L164 136 L256 136 L256 105 L350 105 L350 65 L468 65" className="pb-e-line-primary"/>
      {[72,164,256,350].map((x,i)=><circle key={x} cx={x} cy={[175,136,105,65][i]} r="4" className="pb-e-curve-dot"/>)}
    </svg>
    <div className="pb-e-sketch-foot"><span>五段申报 / 示意</span><span>PRICE →</span></div>
  </div>;
}

function RiskSketch() {
  return <div className="pb-e-sketch pb-e-sketch-risk" aria-hidden="true">
    <span className="pb-e-sketch-eyebrow">ASSESSMENT / 约束校验</span>
    <div className="pb-e-risk-rows">
      {[
        ["01", "成本与收益", "pb-e-bar-one"],
        ["02", "网络与机组", "pb-e-bar-two"],
        ["03", "历史与风险", "pb-e-bar-three"],
      ].map(([number,label,bar])=><div className="pb-e-risk-row" key={number}>
        <div><span>{number}</span><strong>{label}</strong></div>
        <span className={"pb-e-risk-bar "+bar}/>
      </div>)}
    </div>
    <div className="pb-e-sketch-foot"><span>评估维度 / 不代表实际得分</span><span>RESEARCH</span></div>
  </div>;
}

function MarketSketch() {
  return <div className="pb-e-sketch pb-e-sketch-market" aria-hidden="true">
    <span className="pb-e-sketch-eyebrow">MARKET / NETWORK / CLEARING</span>
    <div className="pb-e-market-line">
      <div><span className="pb-e-market-dot"/><strong>市场数据</strong><small>DATA</small></div>
      <i/>
      <div><span className="pb-e-market-dot"/><strong>电网模型</strong><small>GRID</small></div>
      <i/>
      <div><span className="pb-e-market-dot"/><strong>出清结果</strong><small>RESULT</small></div>
    </div>
    <div className="pb-e-sketch-foot"><span>模型之间的关系，可验证、可追溯</span><span>03 / 03</span></div>
  </div>;
}

export default function LandingPage({ workspaceHref }: LandingProps) {
  const [menuOpen,setMenuOpen]=useState(false);
  const [bid,setBid]=useState(310);
  const [step,setStep]=useState(0);
  const percent=(bid-180)/220*100;
  const marker=pointOnDemoCurve(percent);
  const loginHref=import.meta.env.BASE_URL+"login";
  const registerHref=import.meta.env.BASE_URL+"register";
  const closeMenu=()=>setMenuOpen(false);

  useEffect(()=>{
    const oldTitle=document.title;
    const meta=document.querySelector('meta[name="description"]');
    const oldDesc=meta?.getAttribute("content");
    document.title="PowerBid Lab — 电力报价系统小组作业";
    meta?.setAttribute("content","PowerBid 电力市场教学与研究：市场数据、五段报价、策略分析和出清复盘。");
    return ()=>{
      document.title=oldTitle;
      if(oldDesc!=null)meta?.setAttribute("content",oldDesc);
    };
  },[]);

  return <>
    <div className="pb-landing pb-minimal-home pb-editorial-home" id="top">
      <header className="pb-e-header">
        <div className="pb-e-shell pb-e-header-inner">
          <a href="#top" className="pb-e-logo" aria-label="PowerBid 返回首页" onClick={closeMenu}><Brand/></a>
          <nav id="pb-e-mobile-navigation" className={"pb-e-nav"+(menuOpen?" is-open":"")} aria-label="首页导航">
            {sections.map(section=><a key={section.id} href={"#"+section.id} onClick={closeMenu}>{section.name}</a>)}
            <div className="pb-e-mobile-links">
              <a href={loginHref} onClick={closeMenu}>登录</a>
              <a href={registerHref} onClick={closeMenu}>注册</a>
              <a href={workspaceHref} onClick={closeMenu}>进入工作台 <ArrowUpRight size={15}/></a>
            </div>
          </nav>
          <div className="pb-e-header-actions">
            <a className="pb-e-login" href={loginHref}>登录</a>
            <a className="pb-e-register" href={registerHref}>注册</a>
            <a className="pb-e-top-cta" href={workspaceHref}>进入工作台 <ArrowUpRight size={16}/></a>
          </div>
          <button className="pb-e-menu-toggle" type="button" aria-expanded={menuOpen} aria-controls="pb-e-mobile-navigation" aria-label={menuOpen?"关闭导航":"打开导航"} onClick={()=>setMenuOpen(v=>!v)}>
            {menuOpen?<X size={21}/>:<Menu size={21}/>}
          </button>
        </div>
      </header>

      <main>
        <section className="pb-e-hero" aria-labelledby="pb-e-main-title">
          <div className="pb-e-shell pb-e-hero-grid">
            <div className="pb-e-hero-copy">
              <div className="pb-e-eyebrow">POWERBID <span/> ELECTRICITY MARKET LAB</div>
              <h1 id="pb-e-main-title">电力报价系统<br/><em>小组作业</em></h1>
              <p className="pb-e-lead">从市场数据到报价策略，再到市场出清。<br/>让每一步决策都更清晰、更有依据。</p>
              <div className="pb-e-hero-buttons">
                <a className="pb-e-primary" href={workspaceHref}>进入工作台 <ArrowUpRight size={17}/></a>
                <a className="pb-e-secondary" href="#philosophy">了解系统 <ArrowDown size={16}/></a>
              </div>
              <div className="pb-e-hero-foot"><span>研究与教学场景</span><span className="pb-e-divider-dot"/><span>PMSS · 报价与仿真</span></div>
            </div>
            <div className="pb-e-model" aria-label="电网示意模型展示区">
              <PowerConstellation/>
            </div>
          </div>
        </section>

        <section className="pb-e-section pb-e-philosophy" id="philosophy" aria-labelledby="pb-e-philosophy-title">
          <div className="pb-e-shell pb-e-philosophy-grid">
            <div>
              <div className="pb-e-overline">01 / OUR APPROACH</div>
              <h2 id="pb-e-philosophy-title">让复杂的市场，<br/>变得清晰可读。</h2>
            </div>
            <div className="pb-e-philosophy-copy">
              <p>电力市场同时受到供需、机组约束与电网结构影响。我们将数据、模型、报价和验证组织成连贯的研究过程，而不是彼此割裂的工具。</p>
              <div className="pb-e-philosophy-terms"><span>数据依据</span><span>策略逻辑</span><span>结果验证</span></div>
            </div>
          </div>
        </section>

        <section className="pb-e-section pb-e-features" id="capabilities" aria-labelledby="pb-e-features-title">
          <div className="pb-e-shell">
            <div className="pb-e-section-heading">
              <div className="pb-e-overline">02 / WHAT WE DO</div>
              <h2 id="pb-e-features-title">完整的能力，<br/>简洁地呈现。</h2>
              <p>从策略构建到结果复盘，每个环节都服务于一次更可靠的判断。</p>
            </div>
            <div className="pb-e-feature-list">
              <article className="pb-e-feature">
                <div className="pb-e-feature-copy"><span>01 / STRATEGY</span><h3>有依据的报价策略。</h3><p>在机组成本、五段申报和市场约束之间建立联系，比较不同候选策略，而不是给出无法解释的数值。</p></div>
                <StrategySketch/>
              </article>
              <article className="pb-e-feature pb-e-feature-reverse">
                <div className="pb-e-feature-copy"><span>02 / RISK</span><h3>让风险可以被理解。</h3><p>把网络约束、负荷变化和历史误差纳入研究，明确策略的适用条件与局限。</p></div>
                <RiskSketch/>
              </article>
              <article className="pb-e-feature">
                <div className="pb-e-feature-copy"><span>03 / SIMULATION</span><h3>连接市场与电网模型。</h3><p>对接 PMSS 教学环境，清楚区分本地模拟、原版出清及历史案例的真实来源。</p></div>
                <MarketSketch/>
              </article>
            </div>
          </div>
        </section>

        <section className="pb-e-section pb-e-explore" id="explore" aria-labelledby="pb-e-explore-title">
          <div className="pb-e-shell">
            <div className="pb-e-section-heading">
              <div className="pb-e-overline">03 / INTERACTIVE EXPLORATION</div>
              <h2 id="pb-e-explore-title">改变一个变量，<br/>观察一种可能。</h2>
              <p>用一个简单的交互理解报价曲线。下方仅是教学演示，不代表真实市场出清。</p>
            </div>
            <div className="pb-e-explore-panel">
              <div className="pb-e-controls">
                <div className="pb-e-control-top"><span>PRICE / EXPERIMENT 001</span><button type="button" disabled={bid===310} onClick={()=>setBid(310)}><RotateCcw size={13}/> 重置</button></div>
                <h3>报价探索器</h3>
                <p>拖动滑块查看报价位置。真实决策请进入工作台完成模型校验。</p>
                <label htmlFor="pb-e-bid-range">候选申报价格</label>
                <div className="pb-e-value">{bid}<span>元 / MWh</span></div>
                <input id="pb-e-bid-range" type="range" min="180" max="400" step="10" value={bid} aria-valuetext={bid+" 元每兆瓦时"} onChange={e=>setBid(Number(e.target.value))} style={{"--pb-e-percent":percent+"%"} as CSSProperties}/>
                <div className="pb-e-range-label"><span>180</span><span>400</span></div>
                <div className="pb-e-stepper"><button type="button" disabled={bid<=180} onClick={()=>setBid(v=>Math.max(180,v-10))} aria-label="降低报价10元"><Minus size={15}/> 减少</button><button type="button" disabled={bid>=400} onClick={()=>setBid(v=>Math.min(400,v+10))} aria-label="提高报价10元"><Plus size={15}/> 增加</button></div>
              </div>
              <div className="pb-e-explore-chart">
                <div className="pb-e-chart-top"><div><span>ILLUSTRATIVE CURVE</span><strong>报价变化趋势</strong></div><span>交互示意</span></div>
                <svg viewBox="0 0 560 286" className="pb-e-interactive-svg" role="img" aria-label={"交互式报价曲线，当前候选价格 "+bid+" 元每兆瓦时"}>
                  {[40,96,152,208,264].map(y=><line key={y} x1="20" x2="540" y1={y} y2={y} className="pb-e-gridline"/>)}
                  <path d="M20 244 C80 232 118 180 174 174 S276 211 332 128 S438 86 540 38" className="pb-e-price-line"/>
                  <line x1={marker.x} x2={marker.x} y1="27" y2="274" className="pb-e-price-guide"/>
                  <circle cx={marker.x} cy={marker.y} r="9" className="pb-e-price-halo"/>
                  <circle cx={marker.x} cy={marker.y} r="4.3" className="pb-e-price-dot"/>
                </svg>
                <div className="pb-e-chart-bottom"><span>报价 180—400 元 / MWh</span><strong>{bid} <small>元 / MWh</small></strong></div>
              </div>
            </div>
            <div className="pb-e-explore-note"><span>仅供教学与研究 / 图形不是 PMSS 出清证明</span><a href={workspaceHref}>进入完整工作台 <ArrowUpRight size={16}/></a></div>
          </div>
        </section>

        <section className="pb-e-section pb-e-workflow" id="workflow" aria-labelledby="pb-e-workflow-title">
          <div className="pb-e-shell">
            <div className="pb-e-section-heading">
              <div className="pb-e-overline">04 / RESEARCH WORKFLOW</div>
              <h2 id="pb-e-workflow-title">一次完整的研究，<br/>四个清晰的步骤。</h2>
              <p>流程完整，交互不复杂。每一步都有清楚的用途和边界。</p>
            </div>
            <div className="pb-e-steps">
              {steps.map((item,i)=><button key={item.code} type="button" aria-pressed={step===i} className={"pb-e-step"+(step===i?" is-current":"")} onClick={()=>setStep(i)}>
                <span>{item.code} / {item.en}</span><strong>{item.label}</strong><ChevronRight size={17}/>
              </button>)}
            </div>
            <div className="pb-e-step-description" aria-live="polite"><span>{steps[step].code} / {steps[step].en}</span><p>{steps[step].detail}</p></div>
          </div>
        </section>

        <section className="pb-e-final">
          <div className="pb-e-shell pb-e-final-inner">
            <div><span>READY FOR THE NEXT DECISION?</span><h2>让研究，从这里开始。</h2><p>面向电力市场教学与分析的完整工作台。</p></div>
            <a href={workspaceHref} className="pb-e-primary">进入 PowerBid <ArrowRight size={18}/></a>
          </div>
        </section>
      </main>
      <footer className="pb-e-footer"><div className="pb-e-shell pb-e-footer-inner"><Brand/><span>电力市场教学与研究 · 非真实交易建议</span><a href="#top">返回顶部 ↑</a></div></footer>
    </div>
    <Suspense fallback={null}><PublicLiquidGlass/></Suspense>
  </>;
}
