import smirelLogo from "./assets/smirel-logo.png";
import { lazy, Suspense, useEffect, useState } from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight, Menu, X } from "lucide-react";
import "./landing.css";
import "./landing-dark.css";
import "./portal-polish.css";
import "./landing-buttons.css";
import "./landing-showcase-polish.css";
import "./icon-interactions.css";
import "./landing-alma-charcoal.css";
import "./landing-minimal.css";
import PowerConstellation from "./PowerConstellation";

const PublicLiquidGlass = lazy(() => import("./PublicLiquidGlass"));

type LandingProps = { workspaceHref: string };

const capabilities = [
  { number: "01", title: "策略构建", description: "以机组申报和市场数据为基础，探索五段报价与多种决策方案。" },
  { number: "02", title: "市场仿真", description: "连接电网约束和出清分析，让市场变化有迹可循。" },
  { number: "03", title: "风险复盘", description: "对比策略表现，识别不确定性，并追溯每一次结果。" },
];

function Brand() {
  return <span className="pb-brand">
    <img className="pb-brand-smirel" src={smirelLogo} alt="Smirel" width={92} height={30}/>
    <span className="pb-brand-word">PowerBid</span>
  </span>;
}

export default function LandingPage({ workspaceHref }: LandingProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const oldTitle = document.title;
    document.title = "PowerBid Lab — 电力报价系统小组作业";
    const meta = document.querySelector('meta[name="description"]');
    const oldDescription = meta?.getAttribute("content");
    meta?.setAttribute("content", "PowerBid 电力报价系统小组作业 — 简洁的市场研究、报价策略与仿真分析工作台。");
    return () => {
      document.title = oldTitle;
      if (oldDescription !== null && oldDescription !== undefined) meta?.setAttribute("content", oldDescription);
    };
  }, []);

  const closeMenu = () => setMenuOpen(false);
  const loginHref = import.meta.env.BASE_URL + "login";
  const registerHref = import.meta.env.BASE_URL + "register";

  return <>
    <div className="pb-landing pb-minimal-home" id="top">
      <header className="pb-site-header">
        <div className="pb-header-inner">
          <a className="pb-logo-link" href="#top" aria-label="PowerBid 返回首页" onClick={closeMenu}><Brand/></a>
          <nav className={"pb-minimal-nav" + (menuOpen ? " is-open" : "")} aria-label="首页导航">
            <a href="#capabilities" onClick={closeMenu}>产品能力</a>
            <a href="#workflow" onClick={closeMenu}>研究流程</a>
            <a href={loginHref} className="pb-minimal-nav-login" onClick={closeMenu}>登录</a>
            <a href={registerHref} className="pb-minimal-nav-register" onClick={closeMenu}>注册</a>
            <a href={workspaceHref} className="pb-minimal-nav-workspace" onClick={closeMenu}>进入工作台 <ArrowUpRight size={15}/></a>
          </nav>
          <div className="pb-minimal-header-actions">
            <a className="pb-minimal-login" href={loginHref}>登录</a>
            <a className="pb-minimal-register" href={registerHref}>注册</a>
            <a className="pb-minimal-header-cta" href={workspaceHref}>进入工作台 <ArrowUpRight size={15}/></a>
          </div>
          <button type="button" className="pb-minimal-menu-button" aria-expanded={menuOpen} aria-label={menuOpen ? "关闭导航" : "打开导航"} onClick={() => setMenuOpen(open => !open)}>{menuOpen ? <X size={21}/> : <Menu size={21}/>}</button>
        </div>
      </header>

      <main>
        <section className="pb-minimal-hero" aria-labelledby="pb-minimal-title">
          <div className="pb-minimal-container pb-minimal-hero-inner">
            <div className="pb-minimal-hero-copy">
              <div className="pb-minimal-eyebrow"><span className="pb-minimal-eyebrow-line"/>POWERBID / MARKET LAB</div>
              <h1 id="pb-minimal-title">电力报价系统<br/><em>小组作业</em></h1>
              <p className="pb-minimal-lead">把市场数据、报价策略与出清分析，<br/>放进一个更清晰的决策空间。</p>
              <div className="pb-minimal-hero-actions">
                <a className="pb-minimal-primary" href={workspaceHref}>进入决策工作台 <ArrowUpRight size={18}/></a>
                <a className="pb-minimal-secondary" href="#capabilities">了解系统 <ArrowDownRight size={17}/></a>
              </div>
              <p className="pb-minimal-context">教学仿真 · 报价研究 · PMSS 市场分析</p>
            </div>
            <div className="pb-minimal-grid-model">
              <PowerConstellation/>
            </div>
          </div>
        </section>

        <section className="pb-minimal-capabilities" id="capabilities" aria-labelledby="pb-minimal-capabilities-title">
          <div className="pb-minimal-container">
            <div className="pb-minimal-section-title">
              <span>01 / WHAT WE DO</span>
              <h2 id="pb-minimal-capabilities-title">从数据到决策，<br/>一目了然。</h2>
              <p>去掉不必要的复杂，把注意力留给真正重要的分析。</p>
            </div>
            <div className="pb-minimal-capability-grid">
              {capabilities.map(item => <article className="pb-minimal-capability" key={item.number}>
                <span className="pb-minimal-capability-number">{item.number}</span>
                <h3>{item.title}</h3>
                <p>{item.description}</p>
              </article>)}
            </div>
          </div>
        </section>

        <section className="pb-minimal-workflow" id="workflow" aria-labelledby="pb-minimal-workflow-title">
          <div className="pb-minimal-container pb-minimal-workflow-inner">
            <div>
              <span className="pb-minimal-section-eyebrow">02 / THE WORKFLOW</span>
              <h2 id="pb-minimal-workflow-title">观察市场。构建策略。验证结果。</h2>
              <p>从 PMSS 教学案例到本地报价分析，重要步骤始终清晰可追溯。</p>
            </div>
            <a className="pb-minimal-workflow-link" href={workspaceHref}>开始探索 <ArrowRight size={19}/></a>
          </div>
        </section>
      </main>

      <footer className="pb-minimal-footer">
        <div className="pb-minimal-container pb-minimal-footer-inner">
          <Brand/>
          <span>电力市场教学与研究 · 非真实交易建议</span>
          <a href="#top">返回顶部 ↑</a>
        </div>
      </footer>
    </div>
    <Suspense fallback={null}><PublicLiquidGlass/></Suspense>
  </>;
}
