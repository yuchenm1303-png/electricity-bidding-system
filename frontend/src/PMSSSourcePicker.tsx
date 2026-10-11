import { useEffect, useRef, useState } from "react";
import { Database, RefreshCw, ShieldCheck } from "lucide-react";
import {
  describePMSSCoverage, getPMSSCases, getPMSSProjects, getPMSSSnapshot,
  type PMSSCaseRef, type PMSSProjectRef,
} from "./pmssReadOnly";
import type { PMSSInspection } from "./types";
import "./pmss-unified.css";

export function PMSSSourcePicker({ onLoaded, onReset, inspection }: {
  onLoaded: (snapshot: Record<string, unknown>, label: string) => Promise<void>;
  onReset: () => void;
  inspection: PMSSInspection | null;
}) {
  const [projects, setProjects] = useState<PMSSProjectRef[]>([]);
  const [projectId, setProjectId] = useState("");
  const [cases, setCases] = useState<PMSSCaseRef[]>([]);
  const [caseDate, setCaseDate] = useState("");
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingCases, setLoadingCases] = useState(false);
  const [loadingSnapshot, setLoadingSnapshot] = useState(false);
  const [message, setMessage] = useState("");
  const [connected, setConnected] = useState(false);
  const inflight = useRef<AbortController | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoadingProjects(true);
    getPMSSProjects(ctrl.signal).then(items => {
      setProjects(items);
      // One authorized project is the common classroom case; select it automatically.
      setProjectId(current => items.some(p => p.project_id === current)
        ? current : items.length === 1 ? items[0].project_id : "");
      setConnected(true);
      setMessage(items.length ? "" : "当前账号尚无获授权共享的 PMSS 历史案例。普通报价策略和离线快照分析仍可使用；如需此工程，请联系管理员确认课程共享授权。");
    }).catch(error => {
      if (!ctrl.signal.aborted) {
        setConnected(false);
        setMessage(error instanceof Error ? error.message : "工程列表读取失败");
      }
    }).finally(() => { if (!ctrl.signal.aborted) setLoadingProjects(false); });
    return () => ctrl.abort();
  }, [revision]);

  useEffect(() => {
    if (!projectId) {setCases([]); setCaseDate(""); return;}
    const ctrl = new AbortController();
    setLoadingCases(true);
    setCases([]);
    setCaseDate("");
    getPMSSCases(projectId, ctrl.signal).then(items => {
      setCases(items);
      // A new session opens on the latest authorized historical date by default.
      if (items.length) {
        const newest = [...items].sort((a, b) => a.case_date.localeCompare(b.case_date));
        setCaseDate(newest[newest.length - 1].case_date);
      }
      if (!items.length) setMessage("该工程没有可授权读取的历史案例日期。");
      else setMessage("");
    }).catch(error => {
      if (!ctrl.signal.aborted) setMessage(error instanceof Error ? error.message : "日期读取失败");
    }).finally(() => { if (!ctrl.signal.aborted) setLoadingCases(false); });
    return () => ctrl.abort();
  }, [projectId]);

  useEffect(() => () => inflight.current?.abort(), []);

  const chooseProject = (value: string) => {
    inflight.current?.abort();
    setProjectId(value); setCaseDate(""); setMessage(""); onReset();
  };
  const chooseDate = (value: string) => {
    inflight.current?.abort();
    setCaseDate(value); setMessage(""); onReset();
  };
  const load = async () => {
    if (!projectId || !caseDate || loadingSnapshot) return;
    const ctrl = new AbortController();
    inflight.current = ctrl;
    setLoadingSnapshot(true); setMessage("");
    try {
      const snapshot = await getPMSSSnapshot(projectId, caseDate, ctrl.signal);
      if (ctrl.signal.aborted) return;
      const project = projects.find(p => p.project_id === projectId);
      await onLoaded(snapshot, (project?.name || "PMSS 工程") + " / " + caseDate);
      if (!ctrl.signal.aborted) setMessage("已读取服务器脱敏只读快照；本地试算不会写回老师平台。");
    } catch (error) {
      if (!ctrl.signal.aborted) setMessage(error instanceof Error ? error.message : "快照读取失败");
    } finally {
      if (inflight.current === ctrl) inflight.current = null;
      if (!ctrl.signal.aborted) setLoadingSnapshot(false);
    }
  };

  return <div className="pmss-source-panel">
    <div className="pmss-source-heading">
      <div><span className="pmss-source-eyebrow"><Database size={14}/> 授权数据源 · 优先使用</span>
        <h3>选择 PMSS 工程与市场日期</h3>
        <p>选择已经授权保存的真实教学案例即可使用。不需要连接学校 VPN，也不用重新登录老师平台。</p></div>
      <span className="pmss-source-state"><span className={connected ? "pmss-source-dot online" : "pmss-source-dot"}/>
        {loadingProjects ? "正在检查数据源" : connected ? "可查询工程" : "只读接口未就绪"}</span>
    </div>
    <div className="pmss-source-fields">
      <label>市场工程
        <select value={projectId} disabled={!connected || loadingProjects || loadingSnapshot}
          onChange={e => chooseProject(e.target.value)}>
          <option value="">选择授权工程</option>
          {projects.map(project => <option value={project.project_id} key={project.project_id}>{project.name}</option>)}
        </select>
      </label>
      <label>历史案例日期
        <select value={caseDate} disabled={!projectId || loadingCases || loadingSnapshot}
          onChange={e => chooseDate(e.target.value)}>
          <option value="">{loadingCases ? "正在读取日期..." : "选择案例日期"}</option>
          {cases.map(item => <option value={item.case_date} key={item.case_date}>{item.label || item.case_date}</option>)}
        </select>
      </label>
      <button type="button" className="pmss-source-load"
        disabled={!projectId || !caseDate || loadingSnapshot || loadingCases}
        onClick={() => void load()}>
        {loadingSnapshot ? "读取并校验中…" : "加载市场环境"}
      </button>
      <button className="pmss-source-refresh" type="button" title="重新检查工程接口"
        disabled={loadingProjects || loadingSnapshot}
        onClick={() => {setProjects([]);chooseProject("");setConnected(false);setLoadingProjects(true);setRevision(v => v + 1);setMessage("");}}>
        <RefreshCw size={16}/>
      </button>
    </div>
    {message && <p className="pmss-source-message" role="status">{message}</p>}
    {inspection && <p className="pmss-source-coverage"><ShieldCheck size={14}/>
      {inspection.case_date || "日期未标注"} · {describePMSSCoverage(inspection)} · 未执行平台出清</p>}
    <p className="pmss-source-fallback">学校实时登录过期不影响已授权历史案例。没有可用案例时，仍可通过“导入快照”研究，不会提供虚构结果。</p>
  </div>;
}
