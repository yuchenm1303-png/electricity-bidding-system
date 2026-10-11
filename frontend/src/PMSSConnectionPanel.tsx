import { useCallback, useEffect, useState } from "react";
import { Activity, ExternalLink, RefreshCw, ShieldCheck, WifiOff, Wifi, LockKeyhole, Database } from "lucide-react";
import "./pmss-connection.css";

type ConnectionState = {
  operator: "ready" | "unavailable";
  shared_connection: true;
  reconnect_allowed: boolean;
  vpn_container: "running" | "stopped" | "unknown";
  pmss_access: "authorized" | "login_required" | "unreachable" | "unknown";
  retry_after_seconds: number;
  private_case_catalog: "configured" | "not_configured";
  external_login_url: string;
  external_login_is_server_session: boolean;
  writes_to_teacher_platform: false;
};

const STATUS = import.meta.env.BASE_URL + "api/pmss/connection/status";
const RECONNECT = import.meta.env.BASE_URL + "api/pmss/connection/reconnect";
const safePortal = (value: string): string | null => {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "vpn.tsintergy.com" && url.port === "4434"
      ? url.href : null;
  } catch { return null; }
};

export function PMSSConnectionPanel({ enabled }: { enabled: boolean }) {
  const [status, setStatus] = useState<ConnectionState | null>(null);
  const [busy, setBusy] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await fetch(STATUS, { method: "GET", cache: "no-store",
        credentials: "same-origin", headers: { Accept: "application/json" }, signal });
      if (!response.ok) throw new Error(response.status === 401 ? "请先登录 PowerBid 账号。" : "连接状态读取失败");
      const result: ConnectionState = await response.json();
      if (!signal?.aborted) {setStatus(result); setError("");}
    } catch (cause) {
      if (!signal?.aborted) setError(cause instanceof Error ? cause.message : "状态读取失败");
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void refresh(controller.signal);
    const interval = window.setInterval(() => {
      if (!document.hidden) void refresh(controller.signal);
    }, 30000);
    return () => {controller.abort(); window.clearInterval(interval);};
  }, [enabled, refresh]);

  if (!enabled) return null;

  const reconnect = async () => {
    if (restarting || !status?.reconnect_allowed) return;
    if (!window.confirm("学校 VPN 为多人共享。仅在 PMSS 无法访问时，才会重启服务器 EasyConnect。可能短暂影响其他用户，是否继续？")) return;
    setRestarting(true); setMessage(""); setError("");
    try {
      const response = await fetch(RECONNECT, {
        method: "POST", credentials: "same-origin",
        headers: { "Accept": "application/json", "X-PowerBid-Request": "1" },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "重连请求失败");
      setMessage("已执行服务器 VPN 重启。正在检查连接；如果学校要求再次登录，仍需完成身份验证。");
      await refresh();
    } catch (cause) {setError(cause instanceof Error ? cause.message : "无法重新连接");}
    finally {setRestarting(false);}
  };

  const working = status?.pmss_access === "authorized";
  const waiting = status?.pmss_access === "login_required";
  const portal = safePortal(status?.external_login_url ?? "");
  const connectionLabel = working ? "服务器数据通道可用" : waiting ? "学校登录已过期" : status?.operator === "unavailable"
    ? "管理服务未配置" : status?.vpn_container === "stopped" ? "VPN 容器已停止" : "PMSS 连接未验证";

  return <section className="pmss-connection" aria-label="PMSS 连接管理">
    <div className="pmss-connection-top">
      <div>
        <span className="pmss-connection-kicker"><ShieldCheck size={14}/> 所有已登录账号 · 共享连接</span>
        <h3>学校 PMSS 连接管理</h3>
        <p>所有 PowerBid 用户均可查看共享连接状态。学校工程数据仍需各自具备相应授权。</p>
      </div>
      <span className={"pmss-connection-badge" + (working ? " ready" : "")}>
        {working ? <Wifi size={15}/> : <WifiOff size={15}/>} {connectionLabel}
      </span>
    </div>
    <div className="pmss-connection-status">
      <div><span><Activity size={16}/> VPN 容器</span><strong>{status?.vpn_container === "running" ? "运行中" : status?.vpn_container === "stopped" ? "已停止" : "未确认"}</strong></div>
      <div><span><Wifi size={16}/> 服务器 PMSS 通道</span><strong>{working ? "已验证" : waiting ? "需重新登录" : busy ? "检查中" : "不可用 / 未验证"}</strong></div>
      <div><span><Database size={16}/> 历史案例目录</span><strong>{status?.private_case_catalog === "configured" ? "已配置" : "尚未配置"}</strong></div>
    </div>
    <div className="pmss-connection-actions">
      <button type="button" disabled={restarting || !status?.reconnect_allowed}
        className="pmss-connection-restart" onClick={() => void reconnect()}>
        <RefreshCw size={16} className={restarting ? "is-spinning" : ""}/>
        {restarting ? "正在重启…" : "VPN 故障时重连"}
      </button>
      <button type="button" className="pmss-connection-check" disabled={busy} onClick={() => {
        setBusy(true); void refresh().finally(() => setBusy(false));
      }}><Activity size={16}/> 重新检测</button>
      {portal && <a className="pmss-connection-portal" href={portal} target="_blank" rel="noopener noreferrer">
        <ExternalLink size={15}/> 学校登录门户
      </a>}
    </div>
    {working && <p className="pmss-connection-small">服务器通道正常时，为避免中断其他成员，重连操作自动禁用。</p>}
    {waiting && <p className="pmss-connection-small">需要重新完成学校认证；重启容器无法绕过登录。</p>}
    {status?.retry_after_seconds ? <p className="pmss-connection-small">为保护学校会话，重连操作有冷却时间（约 {Math.ceil(status.retry_after_seconds / 60)} 分钟）。</p> : null}
    {error && <p className="pmss-connection-error" role="alert">{error}</p>}
    {message && <p className="pmss-connection-success" role="status">{message}</p>}
    <p className="pmss-connection-notice"><LockKeyhole size={14}/>
      打开学校门户只会登录你当前的浏览器，不等于服务器 VPN 已恢复。所有人的学校平台权限仍由学校独立控制；本页不会共享学校账号、自动提交凭据或报价。
    </p>
  </section>;
}
