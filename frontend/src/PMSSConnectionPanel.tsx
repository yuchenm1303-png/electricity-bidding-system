import { useCallback, useEffect, useState } from "react";
import { Activity, ExternalLink, RefreshCw, ShieldCheck, WifiOff, Wifi, LockKeyhole, Database } from "lucide-react";
import { PMSSBrowserLogin } from "./PMSSBrowserLogin";
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

export function PMSSConnectionPanel({ enabled, isAdmin }: { enabled: boolean; isAdmin: boolean }) {
  const [status, setStatus] = useState<ConnectionState | null>(null);
  const [busy, setBusy] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginLoading, setLoginLoading] = useState(false);
  const closeLogin = useCallback(() => setLoginOpen(false), []);

  const checkSchoolAuthorized = useCallback(async (): Promise<boolean> => {
    try {
      const response = await fetch(STATUS, {
        credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(6000),
      });
      if (!response.ok) return false;
      const next = await response.json() as ConnectionState;
      setStatus(next);
      return next.pmss_access === "authorized";
    } catch { return false; }
  }, []);

  const openSchoolLogin = async () => {
    if (loginLoading) return;
    setLoginLoading(true); setError("");
    try {
      const response = await fetch(import.meta.env.BASE_URL + "api/pmss/connection/browser/availability",
        {credentials: "same-origin", cache: "no-store"});
      const data = await response.json() as {available?: boolean};
      if (!response.ok || !data.available) throw new Error("学校站内登录服务还未部署或正在维护");
      setLoginOpen(true);
    } catch (cause) {setError(cause instanceof Error ? cause.message : "无法打开学校登录");}
    finally {setLoginLoading(false);}
  };

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const timeout = new AbortController();
    const stop = () => timeout.abort();
    if (signal?.aborted) timeout.abort();
    else signal?.addEventListener("abort", stop, { once: true });
    const timer = window.setTimeout(() => timeout.abort(), 8000);
    try {
      const response = await fetch(STATUS, {
        method: "GET", cache: "no-store", credentials: "same-origin",
        headers: { Accept: "application/json" }, signal: timeout.signal,
      });
      if (!response.ok) throw new Error(response.status === 401
        ? "请先登录 PowerBid 账号。" : "服务器连接状态暂时无法读取");
      const result: ConnectionState = await response.json();
      if (!signal?.aborted) { setStatus(result); setError(""); }
    } catch (cause) {
      if (!signal?.aborted) setError(timeout.signal.aborted
        ? "连接状态检查超时，但不影响已授权历史案例的读取。"
        : cause instanceof Error ? cause.message : "状态读取失败");
    } finally {
      window.clearTimeout(timer);
      signal?.removeEventListener("abort", stop);
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
  const catalogReady = status?.private_case_catalog === "configured";
  const portal = safePortal(status?.external_login_url ?? "");
  const liveStatus = working ? "学校实时数据已连接"
    : waiting ? "学校实时会话待重新认证"
      : "学校实时同步未验证";
  const useStatus = catalogReady ? "已保存的历史案例可继续使用"
    : "尚未导入授权历史案例";

  return <section className="pmss-connection is-secondary" aria-label="学校数据维护状态">
    <div className="pmss-connection-top">
      <div>
        <span className="pmss-connection-kicker"><ShieldCheck size={14}/> 数据服务 · 自动检测</span>
        <h3>{useStatus}</h3>
        <p>{catalogReady
          ? "历史案例与学校实时登录相互独立。请在上方选择工程、日期，直接进行本地报价与研究。"
          : "当前暂无已配置的私有案例。授权管理员可在后台准备数据源。"}
        </p>
      </div>
      <span className={"pmss-connection-badge" + (catalogReady ? " ready" : "")}>
        {catalogReady ? <Database size={15}/> : <WifiOff size={15}/>}
        {catalogReady ? "历史案例已配置" : "待配置案例"}
      </span>
    </div>
    <details className="pmss-connection-details">
      <summary> <Activity size={15}/> {isAdmin ? "学校实时同步与管理员维护" : "学校实时连接详情"}
        <span>{working ? "已连接" : waiting ? "同步暂停" : "待检查"}</span>
      </summary>
      <div className="pmss-connection-expanded">
        <p className="pmss-connection-small">{liveStatus}。
          {working ? "后续新案例可在授权范围内同步。" :
            "这不影响已经导入的历史案例。学校强制重新认证时，必须由授权管理员完成。"}
        </p>
        <div className="pmss-connection-status">
          <div><span><Activity size={16}/> VPN 容器</span>
            <strong>{status?.vpn_container === "running" ? "运行中" :
              status?.vpn_container === "stopped" ? "已停止" : "未确认"}</strong></div>
          <div><span><Wifi size={16}/> 学校实时数据</span>
            <strong>{working ? "已验证" : waiting ? "待学校认证" : "未验证"}</strong></div>
          <div><span><Database size={16}/> 已存档案例</span>
            <strong>{catalogReady ? "已配置" : "尚未配置"}</strong></div>
        </div>
        <div className="pmss-connection-actions">
          <button type="button" className="pmss-connection-check" disabled={busy}
            onClick={() => { setBusy(true); void refresh().finally(() => setBusy(false)); }}>
            <Activity size={16}/> 重新检测
          </button>
          {isAdmin && <button type="button"
            disabled={restarting || !status?.reconnect_allowed}
            className="pmss-connection-restart" onClick={() => void reconnect()}>
            <RefreshCw size={16} className={restarting ? "is-spinning" : ""}/>
            {restarting ? "正在重连…" : "确认断线后重启 VPN"}
          </button>}
          {isAdmin && !working && <button type="button" className="pmss-connection-login"
            disabled={loginLoading} onClick={() => void openSchoolLogin()}>
            <LockKeyhole size={15}/> {loginLoading ? "准备学校登录…" : "在 PowerBid 登录学校 PMSS"}
          </button>}
          {isAdmin && portal && <a className="pmss-connection-portal"
            href={portal} target="_blank" rel="noopener noreferrer">
            <ExternalLink size={15}/> 查看学校个人门户
          </a>}
        </div>
        {isAdmin && waiting && <p className="pmss-connection-small">
          管理员提示：学校平台要求重新认证。个人浏览器的网页登录不会自动更新服务器端会话，
          请使用上方“在 PowerBid 登录学校 PMSS”打开受保护的学校登录窗口，认证后将自动更新服务器连接。
          不要重启已正常运行的 VPN 容器来尝试绕过认证。
        </p>}
        {isAdmin && <p className="pmss-connection-notice"><LockKeyhole size={14}/>
          VPN 重连仅在确认网络不可达时开放；学校账号、Cookie 和服务器远程桌面不会交给普通组员。
        </p>}
        {status?.retry_after_seconds ? <p className="pmss-connection-small">
          重连冷却约 {Math.ceil(status.retry_after_seconds / 60)} 分钟。
        </p> : null}
        {error && <p className="pmss-connection-error" role="alert">{error}</p>}
        {message && <p className="pmss-connection-success" role="status">{message}</p>}
      </div>
    </details>
    {isAdmin && <PMSSBrowserLogin show={loginOpen} onClose={closeLogin}
      onConnected={checkSchoolAuthorized}/>}
  </section>;
}
