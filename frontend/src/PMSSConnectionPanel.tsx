import { useCallback, useEffect, useState } from "react";
import { Activity, ExternalLink, RefreshCw, ShieldCheck, WifiOff, Wifi, LockKeyhole, Database } from "lucide-react";
import "./pmss-connection.css";

type ConnectionState = {
  operator: "ready" | "unavailable";
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
      if (!response.ok) throw new Error(response.status === 403 ? "仅管理员能够管理学校 VPN。" : "连接状态读取失败");
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
    if (restarting || !status || status.operator !== "ready" || status.retry_after_seconds > 0) return;
    if (!window.confirm("仅重启服务器上的学校 EasyConnect VPN 容器，不会操作老师的报价或出清。是否继续？")) return;
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
  const connectionLabel = working ? "PMSS 已授权可读" : waiting ? "学校登录已过期" : status?.operator === "unavailable"
    ? "管理服务未配置" : status?.vpn_container === "stopped" ? "VPN 容器已停止" : "PMSS 连接未验证";

  return <section className="pmss-connection" aria-label="PMSS 连接管理">
    <div className="pmss-connection-top">
      <div>
        <span className="pmss-connection-kicker"><ShieldCheck size={14}/> 管理员 · 服务器连接管理</span>
        <h3>学校 PMSS 连接管理</h3>
        <p>连接状态由服务器检查，网页不会接收 VPN 密码或学校会话 Cookie。</p>
      </div>
      <span className={"pmss-connection-badge" + (working ? " ready" : "")}>
        {working ? <Wifi size={15}/> : <WifiOff size={15}/>} {connectionLabel}
      </span>
    </div>
    <div className="pmss-connection-status">
      <div><span><Activity size={16}/> VPN 容器</span><strong>{status?.vpn_container === "running" ? "运行中" : status?.vpn_container === "stopped" ? "已停止" : "未确认"}</strong></div>
      <div><span><Wifi size={16}/> PMSS 授权读取</span><strong>{working ? "已验证" : waiting ? "需重新登录" : busy ? "检查中" : "不可用 / 未验证"}</strong></div>
      <div><span><Database size={16}/> 历史案例目录</span><strong>{status?.private_case_catalog === "configured" ? "已配置" : "尚未配置"}</strong></div>
    </div>
    <div className="pmss-connection-actions">
      <button type="button" disabled={restarting || !status || status.operator !== "ready" || status.retry_after_seconds > 0}
        className="pmss-connection-restart" onClick={() => void reconnect()}>
        <RefreshCw size={16} className={restarting ? "is-spinning" : ""}/>
        {restarting ? "正在重启…" : "一键重连服务器 VPN"}
      </button>
      <button type="button" className="pmss-connection-check" disabled={busy} onClick={() => {
        setBusy(true); void refresh().finally(() => setBusy(false));
      }}><Activity size={16}/> 重新检测</button>
      {portal && <a className="pmss-connection-portal" href={portal} target="_blank" rel="noopener noreferrer">
        <ExternalLink size={15}/> 学校登录门户
      </a>}
    </div>
    {status?.retry_after_seconds ? <p className="pmss-connection-small">为保护学校会话，重连操作有冷却时间（约 {Math.ceil(status.retry_after_seconds / 60)} 分钟）。</p> : null}
    {error && <p className="pmss-connection-error" role="alert">{error}</p>}
    {message && <p className="pmss-connection-success" role="status">{message}</p>}
    <p className="pmss-connection-notice"><LockKeyhole size={14}/>
      打开学校门户只会登录你当前的浏览器，不等于服务器 VPN 已恢复。需要交互式验证码/重新认证时，还需管理员使用服务器安全登录窗口；本页不自动提交凭据或报价。
    </p>
  </section>;
}
