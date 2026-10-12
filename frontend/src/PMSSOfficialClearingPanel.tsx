import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, RefreshCw, ShieldCheck } from "lucide-react";
import type { PMSSStrategyTrio } from "./types";
import "./pmss-live-clearing.css";

type SchoolStatus = { configured: boolean; school_auth: string; live_write_enabled: boolean };
type Prepared = {
  intent_token: string; project_id: string; case_date: string; target_unit_id: string;
  state: string; segments: {startPower: number; endPower: number; price: number}[];
  price_limits: [number, number]; expires_in_seconds: number;
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
  const [selected, setSelected] = useState("");
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [stage, setStage] = useState("IDLE");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [result, setResult] = useState<SchoolResult | null>(null);

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
  const confirmExecute = "执行出清 " + targetUnitId + " " + caseDate;

  async function action(callback: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {await callback();}
    catch (e) {setError(e instanceof Error ? e.message : "老师平台操作失败");}
    finally {setBusy(false);}
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
      {!school ? "检查中…" : school.school_auth === "authorized" ?
        "已验证，可以生成预览" : school.school_auth === "login_required" ?
          "学校要求重新登录，历史研究仍可用" : "学校服务器连接待配置或不可用"}
      <button type="button" disabled={busy} onClick={() => void action(async () => {
        setSchool(await schoolAPI<SchoolStatus>("status"));
      })}><RefreshCw size={14}/> 检测</button>
    </div>
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
