import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowRight, BarChart3, Boxes, ChevronRight, CircleHelp,
  ExternalLink, FileBarChart, LayoutDashboard, Menu, Moon, PanelRightClose, PanelRightOpen,
  Network, Play, RotateCcw, ShieldCheck, SlidersHorizontal, Sparkles, Sun, TrendingUp, X, Zap
} from "lucide-react";
import { loadScenario, runOptimization, fromScenario } from "./api";
import { SettingsPanel } from "./SettingsPanel";
import { UnitsTable } from "./UnitsTable";
import { DashboardOverview } from "./DashboardOverview";
import { CommandSearch } from "./CommandSearch";
import { PMSSWorkspace } from "./PMSSWorkspace";
import { Recommendation, ResultsContent, TrialDetails } from "./Results";
import { type Mode, type Report, type Scenario, type Settings, type WorkspaceView } from "./types";

const navigation: { id: WorkspaceView; label: string; hint: string; icon: typeof LayoutDashboard }[] = [
  { id: "workspace", label: "决策工作台", hint: "概览与操作", icon: LayoutDashboard },
  { id: "units", label: "机组申报数据", hint: "数据编辑", icon: Boxes },
  { id: "pmss", label: "PMSS 市场分析", hint: "只读历史与分段报价", icon: Network },
  { id: "analysis", label: "策略分析", hint: "收益与出清", icon: TrendingUp },
  { id: "risk", label: "压力情景", hint: "风险评估", icon: Activity },
  { id: "trials", label: "试算明细", hint: "记录与导出", icon: FileBarChart },
];
const sourceMap: Record<string, string> = {
  synthetic: "教学仿真数据", course: "课程数据", public: "公开数据",
  platform: "仿真平台数据", unknown: "来源未标记",
};
function validate(config: Settings): string | null {
  if (!Number.isFinite(config.demand_mw) || config.demand_mw < 0 || config.demand_mw > 1000000) return "市场负荷数值无效";
  if (!Number.isFinite(config.interval_hours) || config.interval_hours <= 0 || config.interval_hours > 24) return "结算时段必须在 0–24 小时之间";
  if (config.offers.length === 0) return "请至少添加一台机组";
  if (!config.offers.some(o => o.unit_id === config.target_unit_id)) return "目标机组不在申报清单中";
  const ids = config.offers.map(o => o.unit_id.trim());
  if (ids.some(id => !id) || new Set(ids).size !== ids.length) return "机组编号不能为空或重复";
  if (config.offers.some(o => !Number.isFinite(o.quantity_mw) || !Number.isFinite(o.bid_price) || !Number.isFinite(o.marginal_cost) ||
    o.quantity_mw < 0 || o.bid_price < 0 || o.marginal_cost < 0)) return "机组参数必须为非负有效数字";
  if (config.start > config.stop) return "最低报价不能大于最高报价";
  if (config.step <= 0 || (config.stop - config.start) / config.step > 500) return "报价步长必须大于零，候选数量不能超过 501";
  return null;
}
function Sidebar({ active, change, report, compact, toggle, source }: {
  active: WorkspaceView; change: (view: WorkspaceView) => void; report: Report | null;
  compact: boolean; toggle: () => void; source: string;
}) {
  return <aside className={"sidebar " + (compact ? "collapsed" : "")}>
    <div className="brand">
      <div className="brand-mark"><Activity size={22} strokeWidth={2.4}/><span/></div>
      {!compact && <div className="brand-name"><strong>PowerBid</strong><small>STUDIO / MARKET LAB</small></div>}
      <button type="button" className="sidebar-collapse" title="折叠导航" aria-label="折叠导航" onClick={toggle}><Menu size={17}/></button>
    </div>
    {!compact && <div className="sidebar-section-label">WORKSPACE <span>工作空间</span></div>}
    <nav className="sidebar-nav" aria-label="主导航">
      {navigation.map(item => {
        const Icon = item.icon;
        return <button type="button" key={item.id} title={item.label}
          onClick={() => change(item.id)} className={"nav-entry " + (active === item.id ? "active" : "")}>
          <Icon size={19}/>{!compact && <><span>{item.label}</span>{item.id === "trials" && report && <small className="nav-count">{report.count}</small>}</>}
        </button>;
      })}
      <a className="nav-entry legacy-entry" href="/legacy/" title="老师 PMSS · 原版工作台">
        <ExternalLink size={18} />
        {!compact && <span>老师 PMSS 平台</span>}
      </a>
    </nav>
    <div className="sidebar-spacer"/>
    {!compact && <div className="sidebar-lower">
      <div className="simulation-note"><ShieldCheck size={17}/><div><strong>教学仿真环境</strong><p>React 工作台负责策略模拟。老师平台数据与高级实验功能可通过「老师 PMSS 平台」进入。</p></div></div>
      <div className="data-source"><span className="online-dot"/> {source}</div>
    </div>}
    <div className="sidebar-foot">{!compact ? <><span className="version-dot"/>POWERBID V1.0 <span>·</span> WORKBENCH</> : <span className="version-dot"/>}</div>
  </aside>;
}

function WorkspaceHeader({ view, onRun, running, onReset, onToggleSettings, settingsHidden, disabled }: {
  view: WorkspaceView; onRun: () => void; running: boolean; onReset: () => void;
  onToggleSettings: () => void; settingsHidden: boolean; disabled: boolean;
}) {
  const label: Record<WorkspaceView, [string,string]> = {
    workspace: ["报价策略工作台", "统一管理市场参数、机组申报与报价策略分析"],
    units: ["机组数据管理", "维护模拟市场中的发电机组和申报参数"],
    pmss: ["PMSS 真实市场分析", "导入脱敏快照，查看节点电价与本地五段报价策略"],
    analysis: ["策略分析报告", "用真实计算结果理解报价与收益之间的关系"],
    risk: ["压力情景分析", "检验不同负荷与竞争报价下的策略稳健性"],
    trials: ["试算明细", "完整记录每个候选报价的市场出清结果"],
  };
  return <div className="workspace-header">
    <div className="workspace-heading"><div className="crumbs"><span>工作空间</span><ChevronRight size={13}/><span>{label[view][0]}</span></div>
      <h1>{label[view][0]}</h1><p>{label[view][1]}</p></div>
    <div className="header-actions">
      {view !== "pmss" && <>
      <button type="button" className="outline-button reset-button" title="恢复示例数据" onClick={onReset}><RotateCcw size={16}/> <span>恢复示例</span></button>
      <button type="button" className="outline-button settings-toggle" title="展开或收起策略参数" onClick={onToggleSettings}>
        {settingsHidden ? <PanelRightOpen size={16}/> : <PanelRightClose size={16}/>}
        <span>参数</span>
      </button>
      <button type="button" className={"primary-button run-button" + (running ? " is-running" : "")} disabled={running || disabled} onClick={onRun}>
        {running ? <span className="button-spinner"/> : <Play size={16} fill="currentColor"/>}
        <span>{running ? "正在优化..." : "运行报价分析"}</span><ArrowRight size={15}/>
      </button>
      </>}
    </div>
  </div>;
}
function GettingStarted({ onRun, running }: { onRun: () => void; running: boolean }) {
  return <section className="quick-guide">
    <div><div className="panel-kicker">NEXT STEP / START HERE</div><h3>配置就绪，开始寻找更优报价</h3>
      <p>模型将依次尝试候选价格，比较出清电量、市场价格和利润。结果会直接显示在下方分析区域。</p>
      <div className="guide-steps"><span><b>01</b> 检查机组</span><ChevronRight size={13}/><span><b>02</b> 设置报价</span><ChevronRight size={13}/><span><b>03</b> 查看结果</span></div>
    </div>
    <button type="button" className="guide-action" onClick={onRun} disabled={running}><Zap size={17}/>{running ? "正在计算" : "开始策略分析"}<ArrowRight size={15}/></button>
  </section>;
}
function AnalysisTeaser({ report, onNavigate }: { report: Report | null; onNavigate: (view: WorkspaceView) => void }) {
  if (!report) return null;
  return <button type="button" className="analysis-teaser" onClick={() => onNavigate("analysis")}>
    <span className="analysis-teaser-icon"><BarChart3 size={17}/></span>
    <span><strong>查看完整分析报告</strong><small>{report.count} 个候选报价已试算 · 包含收益曲线和明细</small></span>
    <ArrowRight size={16}/>
  </button>;
}
export default function App() {
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [config, setConfig] = useState<Settings | null>(null);
  const [view, setView] = useState<WorkspaceView>("workspace");
  const [report, setReport] = useState<Report | null>(null);
  const [reportSignature, setReportSignature] = useState("");
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [sidebarCompact, setSidebarCompact] = useState(false);
  const [settingsHidden, setSettingsHidden] = useState(true);
  const [drawerMounted, setDrawerMounted] = useState(false);
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    window.localStorage.getItem("powerbid-theme") === "dark" ? "dark" : "light"
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("powerbid-theme", theme);
  }, [theme]);
  const [mobileNav, setMobileNav] = useState(false);
  const [pmssVisited, setPmssVisited] = useState(false);
  useEffect(() => {
    if (!settingsHidden) {
      const frame = window.requestAnimationFrame(() => setDrawerVisible(true));
      return () => window.cancelAnimationFrame(frame);
    }
    setDrawerVisible(false);
    if (drawerMounted) {
      const timeout = window.setTimeout(() => setDrawerMounted(false), 350);
      return () => window.clearTimeout(timeout);
    }
  }, [settingsHidden, drawerMounted]);
  const openSettings = () => {
    setDrawerMounted(true);
    setSettingsHidden(false);
  };
  const closeSettings = () => setSettingsHidden(true);
  const toggleSettings = () => settingsHidden ? openSettings() : closeSettings();
  useEffect(() => {
    let mounted = true;
    loadScenario().then(data => {
      if (!mounted) return;
      setScenario(data);
      setConfig(fromScenario(data));
    }).catch(e => { if (mounted) setError(e.message ?? "场景读取失败"); });
    return () => { mounted = false; };
  }, []);
  const signature = useMemo(() => config ? JSON.stringify(config) : "", [config]);
  const stale = !!report && reportSignature !== signature;
  const validationError = config ? validate(config) : null;
  const update = (next: Settings) => { setConfig(next); setError(""); };
  const setMode = (mode: Mode) => {
    if (config) update({ ...config, mode });
  };
  const changeView = (next: WorkspaceView) => {
    if (next === "pmss") setPmssVisited(true);
    setView(next);
    setMobileNav(false);
    document.querySelector(".app-main")?.scrollTo({ top: 0, behavior: "auto" });
    if (next === "risk" && config && config.mode !== "risk") setMode("risk");
  };
  const reset = () => {
    if (!scenario) return;
    setConfig(fromScenario(scenario));
    setReport(null);
    setReportSignature("");
    setError("");
    setView("workspace");
  };
  const run = useCallback(async () => {
    if (!config || running) return;
    const issue = validate(config);
    if (issue) { setError(issue); return; }
    setRunning(true);
    setError("");
    const snapshot = JSON.stringify(config);
    try {
      const result = await runOptimization(config);
      setReport(result);
      setReportSignature(snapshot);
    } catch (e) {
      setError(e instanceof Error ? e.message : "分析失败");
    } finally {
      setRunning(false);
    }
  }, [config, running]);
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if (view !== "pmss" && (e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        void run();
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [run, view]);
  return <div className="app">
    <div className="mobile-topbar"><button type="button" className="icon-button" onClick={() => setMobileNav(true)} aria-label="打开菜单"><Menu size={20}/></button>
      <strong><Activity size={17}/> PowerBid Studio</strong><button type="button" className="icon-button" title="切换参数面板" onClick={toggleSettings}><SlidersHorizontal size={19}/></button></div>
    {mobileNav && <button type="button" className="mobile-backdrop" aria-label="关闭菜单" onClick={() => setMobileNav(false)}/>}
    <div className={mobileNav ? "mobile-sidebar-visible" : ""}>
      <Sidebar active={view} change={changeView} report={report} compact={sidebarCompact}
        toggle={() => setSidebarCompact(v => !v)} source={view === "pmss" ? "PMSS / 脱敏快照" : sourceMap[scenario?.data_source ?? "unknown"] ?? "来源未标记"}/>
      {mobileNav && <button type="button" className="mobile-close" onClick={() => setMobileNav(false)} aria-label="关闭菜单"><X size={21}/></button>}
    </div>
    <div className="app-main">
      <header className="global-header">
        <div className="ta-header-left">
          <button className="ta-menu-toggle" type="button" onClick={() => setSidebarCompact(v => !v)}
            aria-label={sidebarCompact ? "展开侧边导航" : "折叠侧边导航"}><Menu size={19}/></button>
          <CommandSearch destinations={navigation} onNavigate={changeView}/>
        </div>
        <div className="global-right">
          <button className="ta-header-icon" type="button"
            onClick={() => setTheme(v => v === "light" ? "dark" : "light")}
            aria-label={theme === "light" ? "切换为深色模式" : "切换为浅色模式"}
            title={theme === "light" ? "切换为深色模式" : "切换为浅色模式"}>
            <span key={theme} className="theme-glyph">{theme === "light" ? <Moon size={19}/> : <Sun size={19}/>}</span>
          </button>
          <span className="environment-pill"><span className="online-dot"/> 教学模拟环境</span>
          {view !== "pmss" && <button className="ta-header-icon" type="button" title="打开策略参数" aria-label="打开策略参数"
            onClick={openSettings}><SlidersHorizontal size={19}/></button>}
          <span className="avatar-mark">PB</span>
        </div>
      </header>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button type="button" onClick={() => setError("")} aria-label="关闭错误"><X size={16}/></button></div>}
      {!config ? <div className="loading-workspace"><div className="loading-symbol"><Activity size={27}/></div><h2>{error ? "无法加载市场场景" : "正在载入报价工作台"}</h2><p>PowerBid 正在连接本地仿真计算服务...</p><button className="outline-button" onClick={() => window.location.reload()}>重新加载</button></div> :
      <div className="content-shell">
        <WorkspaceHeader view={view} onRun={() => void run()} running={running} onReset={reset}
          onToggleSettings={toggleSettings} settingsHidden={settingsHidden} disabled={!!validationError}/>
        {view !== "pmss" && validationError && <div className="validation-banner"><CircleHelp size={15}/>{validationError}</div>}
        <div className="view-stage" key={view}>
        {view === "workspace" && <>
          <DashboardOverview offers={config.offers} demand={config.demand_mw}
            targetId={config.target_unit_id} report={report}
            onNavigate={() => changeView(report ? "analysis" : "units")}/>
          <div className="ta-secondary-section">
            <div className="ta-section-heading"><div><span>WORKSPACE DATA</span><h2>机组与报价数据</h2>
              <p>编辑机组申报信息后运行策略计算。所有修改会参与下一次模拟。</p></div>
              <span className="ta-section-hint">共 {config.offers.length} 台发电机组</span>
            </div>
            <div className="ta-work-grid">
              <UnitsTable offers={config.offers} targetId={config.target_unit_id}
                onChange={offers => setConfig(previous => previous ? { ...previous, offers } : previous)}
                onTarget={target_unit_id => setConfig(previous => previous ? { ...previous, target_unit_id } : previous)}/>
              <Recommendation report={report} stale={stale} running={running} onRun={() => void run()}/>
            </div>
          </div>
          {!report && <GettingStarted running={running} onRun={() => void run()}/>}
          {report && <><AnalysisTeaser report={report} onNavigate={changeView}/>
            <ResultsContent report={report} stale={stale} running={running} onRun={() => void run()} compact/>
          </>}
        </>}
        {view === "units" && <>
          <div className="section-note"><Boxes size={18}/><span>直接修改数据表格即可更新本轮场景。点击左侧圆点将机组设为优化目标。</span></div>
          <UnitsTable expanded offers={config.offers} targetId={config.target_unit_id}
            onChange={offers => setConfig(previous => previous ? { ...previous, offers } : previous)}
            onTarget={target_unit_id => setConfig(previous => previous ? { ...previous, target_unit_id } : previous)}/>
        </>}
        {view === "analysis" && <ResultsContent report={report} stale={stale} running={running} onRun={() => void run()}/>}
        {view === "risk" && <>
          {config.mode !== "risk" && <div className="section-note"><InfoIcon/> 点击右侧参数中的风险模式，运行压力情景分析。</div>}
          <ResultsContent report={report?.mode === "risk" ? report : null} stale={stale} running={running} onRun={() => void run()}/>
        </>}
        {view === "trials" && <TrialDetails report={report}/>}
        </div>
        {pmssVisited && <div className="pmss-persistent-stage" style={{display:view === "pmss" ? "block" : "none"}}>
          <PMSSWorkspace/>
        </div>}
        <footer className="app-footer"><span>POWERBID STUDIO · 市场策略研究</span><span>Simulation only · Not for live trading</span></footer>
      </div>}
    </div>
    {config && drawerMounted && <div className={"ta-drawer-layer " + (drawerVisible ? "is-open" : "is-closing")}>
      <button className="ta-settings-overlay" type="button" aria-label="关闭策略参数" onClick={closeSettings}/>
      <SettingsPanel config={config} onChange={update} onClose={closeSettings}
        collapsed={false} onModeChange={setMode}/>
    </div>}
  </div>;
}

function InfoIcon() { return <Sparkles size={18}/>; }
