import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, RefreshCw, ShieldCheck } from "lucide-react";
import type { PMSSStrategyTrio } from "./types";
import "./pmss-live-clearing.css";

type SchoolStatus = { configured: boolean; school_auth: string; live_write_enabled: boolean;
  read_only_school_auth?: string };
type SchoolPreflight = {
  source: "TEACHER_PMSS_BRIDGE_READ_ONLY"; school_authenticated: true;
  read_only: true; teacher_write_performed: false; teacher_clearing_executed: false;
  project_name: string; case_date: string; target_unit_id: string;
  target_unit_name: string; school_unit_capacity_mva: number;
  school_case_mapped: boolean; price_limits: [number,number]; max_segments: number;
  same_curve_all_day: boolean; existing_school_bid_blocks: number;
  original_cost_fields_present: boolean; original_write_configured: boolean;
};
type Prepared = {
  intent_token: string; project_id: string; case_date: string; target_unit_id: string;
  state: string; segments: {startPower: number; endPower: number; price: number}[];
  price_limits: [number, number]; expires_in_seconds: number;
};
type SchoolAcceptance = {
  source: "TEACHER_PMSS_ORIGINAL"; project_id: string; case_date: string;
  target_unit_id: string; target_unit_name: string; state: string;
  school_bid_readback_verified: boolean; school_bid_prices: number[];
  school_clearing_result_changed: boolean; school_converged: boolean;
  school_relaxed: number | null; school_iterations: number | null;
  school_total_system_cost_raw: number | null;
  school_total_system_run_cost_raw: number | null;
  school_total_system_start_cost_raw: number | null;
  school_nodal_count: number; school_branch_count: number;
  hourly_complete: boolean; clearing_finished: boolean;
  accepted_mwh: number | null; hourly_accepted_mw: number[];
  hourly_clearing_prices: number[]; hourly_income_raw: number[];
  school_income_raw_sum: number | null;
  school_income_unit_verified: false; direct_profit_comparison_valid: false;
};
type SchoolResult = {
  state: string; source: string; case_date: string; target_unit_id: string;
  school_clearing_status: Record<string, unknown>;
  school_result_overview: Record<string, unknown>;
  teacher_response_signed: false;
  candidate_causality_independently_verified: false;
};

async function schoolAPI<T>(path: string, payload?: Record<string, unknown>): Promise<T> {
  const response = await fetch("/api/pmss/live/" + path, {
    method: payload ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
    headers: {Accept: "application/json", ...(payload
      ? {"Content-Type": "application/json", "X-PowerBid-Request": "1"} : {})},
    ...(payload ? {body: JSON.stringify(payload)} : {}),
  });
  let data: Record<string, unknown>;
  try { data = await response.json() as Record<string, unknown>; }
  catch { throw new Error("学校出清接口未返回有效 JSON"); }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail :
    "学校出清服务返回 HTTP " + response.status);
  return data as T;
}

/** Original school PMSS writes require TWO separate confirmations. */
export function PMSSOfficialClearingPanel({
  projectId, caseDate, targetUnitId, trio,
}: {
  projectId: string; caseDate: string; targetUnitId: string; trio: PMSSStrategyTrio;
}) {
  const [school, setSchool] = useState<SchoolStatus | null>(null);
  const [preflight, setPreflight] = useState<SchoolPreflight | null>(null);
  const [selected, setSelected] = useState("");
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [stage, setStage] = useState("IDLE");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [result, setResult] = useState<SchoolResult | null>(null);
  const [acceptance, setAcceptance] = useState<SchoolAcceptance | null>(null);

  useEffect(() => {
    let active = true;
    void schoolAPI<SchoolStatus>("status").then(data => {
      if (active) setSchool(data);
    }).catch(() => {
      if (active) setSchool({configured: false, school_auth: "unavailable",
        live_write_enabled: false});
    });
    return () => {active = false;};
  }, []);

  const usable = trio.target_unit_id === targetUnitId ?
    trio.candidates.filter(item => item.price_blocks.length === 5 &&
      item.price_blocks.some(block => block[2] > 0) &&
      item.price_blocks.every(block =>
        block.length === 3 && block.every(Number.isFinite))) : [];
  const profile = usable.find(item => item.profile === selected);
  const confirmSubmit = "提交报价 " + targetUnitId + " " + caseDate;
  const verifiedPreflight = preflight?.case_date === caseDate &&
    preflight.target_unit_id === targetUnitId ? preflight : null;
  const confirmExecute = "执行出清 " + targetUnitId + " " + caseDate;
  const currentAcceptance = acceptance?.project_id === projectId &&
    acceptance.case_date === caseDate &&
    acceptance.target_unit_id === targetUnitId ? acceptance : null;
  const localBalanced = trio.candidates.find(c => c.profile.includes("均衡"));
  const formatValue = (value: number | null, digits = 2) =>
    value === null ? "—" : value.toLocaleString("zh-CN", {
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    });

  async function action(callback: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {await callback();}
    catch (e) {setError(e instanceof Error ? e.message : "老师平台操作失败");}
    finally {setBusy(false);}
  }

  async function preflightSchool() {
    await action(async () => {
      const params = new URLSearchParams({project_id:projectId,
        case_date:caseDate, target_unit_id:targetUnitId});
      const report = await schoolAPI<SchoolPreflight>("school-preflight?" + params.toString());
      setPreflight(report);
      setNotice("已直接读取学校原版工程、日期、机组及报价规则；本次仅做只读核验，未提交或出清。");
    });
  }

  async function checkLatestAcceptance() {
    await action(async () => {
      const query = new URLSearchParams({
        project_id: projectId, case_date: caseDate, target_unit_id: targetUnitId,
      });
      const data = await schoolAPI<SchoolAcceptance>(
        "latest-acceptance?" + query.toString()
      );
      setAcceptance(data);
      setNotice(data.clearing_finished ?
        "老师 PMSS 已返回新出清结果：基线变化、收敛及 24 小时数据完整性均通过。" :
        "已读取老师出清记录，但尚未满足完整验收条件。");
    });
  }

  async function prepare() {
    if (!profile || !school?.live_write_enabled) return;
    await action(async () => {
      const p = await schoolAPI<Prepared>("prepare", {
        project_id: projectId, case_date: caseDate, target_unit_id: targetUnitId,
        segments: profile.price_blocks.map(([start_power, end_power, price]) =>
          ({start_power, end_power, price})),
      });
      setPrepared(p);setStage(p.state);setTyped("");
      setNotice("已根据学校实时规则和原报价成本生成真实预览；尚未修改学校平台。");
    });
  }

  async function submit() {
    if (!prepared || stage !== "PREPARED" || typed !== confirmSubmit) return;
    await action(async () => {
      setStage("UNKNOWN_SAVE");
      const r = await schoolAPI<{state: string}>("submit", {
        intent_token: prepared.intent_token, confirmation: typed,
      });
      setStage(r.state);setTyped("");
      setNotice("学校接口已响应保存；必须先读回验证五段报价。");
    });
  }

  async function verify() {
    if (!prepared || !["SAVE_ACKNOWLEDGED", "UNKNOWN_SAVE"].includes(stage)) return;
    await action(async () => {
      const r = await schoolAPI<{state: string; readback_verified: boolean}>(
        "verify-saved", {intent_token: prepared.intent_token, confirmation: "只读核对"},
      );
      if (r.readback_verified) {setStage(r.state);setNotice("学校保存的报价与预览一致。");}
      else setError("学校返回的报价不一致，禁止出清，不会重新提交。");
    });
  }

  async function execute() {
    if (!prepared || stage !== "VERIFIED_SAVED" || typed !== confirmExecute) return;
    await action(async () => {
      setStage("UNKNOWN_CLEARING");
      const r = await schoolAPI<{state: string}>("execute", {
        intent_token: prepared.intent_token, confirmation: typed,
      });
      setStage(r.state);setTyped("");
      setNotice("学校 PMSS 已接受出清执行请求，可只读查询结果。");
    });
  }

  async function refreshResult() {
    if (!prepared || !["CLEARING_REQUESTED", "UNKNOWN_CLEARING"].includes(stage)) return;
    await action(async () => {
      const params = new URLSearchParams({intent_token: prepared.intent_token});
      setResult(await schoolAPI<SchoolResult>("result?" + params.toString()));
      setNotice("已从老师 PMSS 读取原版出清状态。");
    });
  }

  if (!projectId || !targetUnitId || !trio.candidates.length) return null;

  return <section className="pmss-live-panel" aria-label="老师 PMSS 原版出清">
    <header className="pmss-live-header">
      <div><small>OFFICIAL PMSS ENGINE</small><h3>调用老师的原版出清引擎</h3>
        <p>真实保存报价、执行学校市场出清，再读取结果。不同于本地 DC 模拟。</p></div>
      <span><ShieldCheck size={15}/> 分步人工确认</span>
    </header>
    <div className="pmss-live-connect">
      <strong>学校应用会话：</strong>
      {!school ? "检查中…" : school.live_write_enabled ?
        "原版出清连接已核验" : school.read_only_school_auth === "authorized" ?
        "学校只读会话已验证 · 原版报价写入尚待独立配置" :
        school.read_only_school_auth === "login_required" ?
        "学校登录会话已过期" : "学校实时连接不可用或待配置"}
      <button type="button" disabled={busy} onClick={() => void action(async () => {
        setSchool(await schoolAPI<SchoolStatus>("status"));
      })}><RefreshCw size={14}/> 检测</button>
    </div>
    <div className="pmss-live-connect">
      <strong>学校实时数据只读核验：</strong>
      <button type="button" disabled={busy ||
          school?.read_only_school_auth !== "authorized"}
        onClick={() => void preflightSchool()}>核验选定工程、日期、机组及五段规则（不提交）</button>
    </div>
    {verifiedPreflight && <div className="pmss-live-preview">
      <div><strong>学校工程</strong><span>{verifiedPreflight.project_name} / {verifiedPreflight.case_date}</span></div>
      <div><strong>学校机组</strong><span>{verifiedPreflight.target_unit_name} · {verifiedPreflight.school_unit_capacity_mva} MVA</span></div>
      <div><strong>学校日前市场</strong><span>24小时共用曲线：{verifiedPreflight.same_curve_all_day ? "是" : "否"} · 最多 {verifiedPreflight.max_segments} 段</span></div>
      <div><strong>实时报价范围</strong><span>{verifiedPreflight.price_limits[0]}～{verifiedPreflight.price_limits[1]}</span></div>
      <div><strong>学校原报价读取</strong><span>{verifiedPreflight.existing_school_bid_blocks} 段 · 原始成本字段：{verifiedPreflight.original_cost_fields_present ? "已核验" : "缺失"}</span></div>
      <p>只读学校原始数据，尚未保存新报价或执行出清。学校读写权限与本地策略风控分开核验。</p>
    </div>}
    <div className="pmss-live-connect">
      <strong>老师原版最新真实出清：</strong>
      <button type="button" disabled={busy || !school?.live_write_enabled}
        onClick={() => void checkLatestAcceptance()}>
        读取本机组真实出清结果（只读）
      </button>
    </div>
    {currentAcceptance && <div className="pmss-live-results" role="region"
      aria-label="老师原版最新出清验收">
      <h4>老师 PMSS 原版出清验收</h4>
      <div><span>状态</span><strong>{currentAcceptance.clearing_finished ?
        "真实出清完成 · 已收敛" : "尚未通过完整验收"}</strong></div>
      <div><span>工程 / 日期 / 机组</span><strong>
        {currentAcceptance.project_id} / {currentAcceptance.case_date} /
        {currentAcceptance.target_unit_name}</strong></div>
      <div><span>学校已保存的五段报价</span><strong>
        {currentAcceptance.school_bid_prices.join(" / ")}
        {currentAcceptance.school_bid_readback_verified ? " · 读回一致" : " · 待核验"}
      </strong></div>
      <div><span>真实中标电量（24小时）</span>
        <strong>{formatValue(currentAcceptance.accepted_mwh)} MWh</strong></div>
      <div><span>原始收入字段合计（单位待核实）</span>
        <strong>{formatValue(currentAcceptance.school_income_raw_sum, 4)}</strong></div>
      <div><span>老师原版市场系统总成本（原始接口数值）</span>
        <strong>{formatValue(currentAcceptance.school_total_system_cost_raw)}</strong></div>
      <div><span>求解与网络数据</span><strong>
        {currentAcceptance.school_iterations ?? "—"} 次迭代 /
        {currentAcceptance.school_nodal_count} 节点 /
        {currentAcceptance.school_branch_count} 线路</strong></div>
      <div><span>新的出清结果相对执行前基线</span><strong>
        {currentAcceptance.school_clearing_result_changed ? "已发生变化" : "未验证变化"}</strong></div>
      {localBalanced && <div><span>PowerBid 均衡方案本地模拟利润（非学校收益）</span>
        <strong>{formatValue(localBalanced.expected_dc_margin)}</strong></div>}
      <p>学校原始收入字段的计量单位尚未独立核实，也未获得 G31 真实成本分摊。
        因此不能把学校收入与 PowerBid 本地利润直接相减或声称收益误差率。
        该报告只读取服务器已保存的人工确认操作记录，不会再次提交报价或执行出清。</p>
      {currentAcceptance.hourly_complete && <details className="pmss-live-hourly">
        <summary>查看 G31 全天 24 小时中标量、价格与原始收入</summary>
        <table><thead><tr><th>时段</th><th>中标 MW</th><th>价格</th><th>收入原始值</th></tr></thead>
          <tbody>{currentAcceptance.hourly_accepted_mw.map((mw, index) =>
            <tr key={index}><td>{index + 1}</td>
              <td>{formatValue(mw, 3)}</td>
              <td>{formatValue(currentAcceptance.hourly_clearing_prices[index])}</td>
              <td>{formatValue(currentAcceptance.hourly_income_raw[index], 4)}</td>
            </tr>)}</tbody></table>
      </details>}
    </div>}
    <p className="pmss-live-warning"><AlertTriangle size={16}/>
      三类本地策略尚未经过老师 PMSS 验证，部分机组物理约束也尚未核实。实际能否接受报价由学校实时规则检查；操作会修改学校对应案例的报价与结果；
      请只选择本次课程仿真实验要验证的报价。</p>
    <div className="pmss-live-pick">
      <label htmlFor="pmss-live-profile">选择需要送入学校验证的研究策略</label>
      <select id="pmss-live-profile" value={selected} disabled={busy || !!prepared}
        onChange={e => {setSelected(e.target.value);setError("");setTyped("");}}>
        <option value="">请选择策略（不会自动采用最高利润）</option>
        {usable.map(item => <option key={item.profile} value={item.profile}>
          {item.profile} · 本地研究方案
        </option>)}
      </select>
      {profile && <div className="pmss-live-prices">
        {profile.price_blocks.map(([start,end,price],i) =>
          <span key={i}>第{i+1}段 {start}–{end} MW · {price}</span>)}
      </div>}
    </div>
    {stage === "IDLE" && <button type="button" className="pmss-live-action"
      disabled={busy || !profile || !school?.live_write_enabled}
      onClick={() => void prepare()}>读取学校规则并预览真实提交</button>}
    {prepared && <div className="pmss-live-preview">
      <div><strong>当前目标</strong><span>{prepared.project_id} / {prepared.case_date} / {prepared.target_unit_id}</span></div>
      <div><span>学校价格上下限</span><strong>{prepared.price_limits[0]}～{prepared.price_limits[1]}</strong></div>
      <div><span>提交的五段价格</span><strong>{prepared.segments.map(p => p.price).join(" / ")}</strong></div>
      <p>每次学校写入只发送一次。超时后不自动重试，必须先只读核对。</p>
    </div>}
    {prepared && stage === "PREPARED" && <div className="pmss-live-confirm">
      <label>要真实保存报价，请输入：<code>{confirmSubmit}</code></label>
      <input value={typed} maxLength={180} onChange={e => setTyped(e.target.value)}
        placeholder={confirmSubmit} autoComplete="off"/>
      <button type="button" disabled={busy || typed !== confirmSubmit}
        onClick={() => void submit()}>确认提交五段报价到学校 PMSS</button>
    </div>}
    {prepared && ["SAVE_ACKNOWLEDGED","UNKNOWN_SAVE"].includes(stage) &&
      <button type="button" className="pmss-live-action" disabled={busy}
        onClick={() => void verify()}>只读核对学校保存的五段报价</button>}
    {prepared && stage === "VERIFIED_SAVED" && <div className="pmss-live-confirm">
      <p><CheckCircle2 size={15}/> 保存内容已通过读回核对。</p>
      <label>要真实启动学校出清，请输入：<code>{confirmExecute}</code></label>
      <input value={typed} maxLength={180} onChange={e => setTyped(e.target.value)}
        placeholder={confirmExecute} autoComplete="off"/>
      <button type="button" disabled={busy || typed !== confirmExecute}
        onClick={() => void execute()}>确认执行老师 PMSS 出清</button>
    </div>}
    {prepared && ["UNKNOWN_CLEARING","CLEARING_REQUESTED"].includes(stage) &&
      <button type="button" className="pmss-live-action" disabled={busy}
        onClick={() => void refreshResult()}>只读查询老师 PMSS 原版出清结果</button>}
    {result && <div className="pmss-live-results">
      <h4>老师 PMSS 出清结果摘要</h4>
      {Object.entries({...result.school_clearing_status,
        ...result.school_result_overview}).map(([key,value]) =>
        <div key={key}><span>{key}</span><strong>{String(value)}</strong></div>)}
      <small>学校原版接口返回的结果；真实因果归属仍以学校官方记录为准。
        不得把本地模拟利润当成真实收益。</small>
    </div>}
    {notice && <p role="status" className="pmss-live-success">{notice}</p>}
    {error && <p role="alert" className="pmss-live-error">{error}</p>}
    {prepared && <p className="pmss-live-state">操作状态：<b>{stage}</b></p>}
    <footer>普通组员不需要管理 VPN；学校凭据不会进入浏览器或 GitHub。</footer>
  </section>;
}
