import { useEffect, useRef, useState } from "react";
import { ExternalLink, Keyboard, LockKeyhole, RefreshCw, X } from "lucide-react";
import "./pmss-school-login.css";
import { browserImagePoint } from "./pmssBrowserCoordinates";
import { createFramePump } from "./pmssFramePump";

const BASE = import.meta.env.BASE_URL + "api/pmss/connection/browser/";

type BrowserAction =
  | { action: "open" }
  | { action: "click"; x: number; y: number }
  | { action: "text"; text: string }
  | { action: "key"; key: string }
  | { action: "scroll"; dy: -1 | 1 };

export function PMSSBrowserLogin({
  show, onClose, onConnected,
}: { show: boolean; onClose: () => void; onConnected: () => Promise<boolean> }) {
  const [frameUrl, setFrameUrl] = useState("");
  const [showRemote, setShowRemote] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [frameError, setFrameError] = useState("");
  const [hint, setHint] = useState("点击画面里的输入框，然后在键盘上正常输入。");
  const image = useRef<HTMLImageElement>(null);
  const surface = useRef<HTMLDivElement>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const actionGeneration = useRef(0);
  const textBuffer = useRef("");
  const typingTimer = useRef<number | null>(null);
  const pendingActions = useRef(0);
  const requestFrame = useRef<() => void>(() => {});

  async function post(data: BrowserAction): Promise<void> {
    const response = await fetch(BASE + "action", {
      signal: AbortSignal.timeout(12000),
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-PowerBid-Request": "1" },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      if (response.status === 409) {
        void onConnected().then(ok => { if (ok) onClose(); }).catch(() => {});
      }
      const payload = await response.json().catch(() => ({})) as {detail?: string};
      throw new Error(payload.detail || "学校登录窗口暂时无法控制");
    }
    // Refresh on success; input focus is managed by the remote browser.
    if (data.action === "click") {
      const feedback = await response.json().catch(() => ({})) as {focused_input?: boolean};
      setHint(feedback.focused_input
        ? "已选中学校输入框。现在直接键入用户名或密码。"
        : "点击已送达学校页面；如需输入，请点击对应输入框。");
    }
    setError("");
  }

  async function loginSchool(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || !username || !password) return;
    setSubmitting(true);
    pendingActions.current += 1;
    setError("");
    setHint("正在将账号信息一次性提交到学校原版登录页面…");
    try {
      // One request for the complete school form, not one round trip per key.
      const response = await fetch(BASE + "login", {
        signal: AbortSignal.timeout(12000),
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: {"Content-Type":"application/json", "X-PowerBid-Request":"1"},
        body: JSON.stringify({username, password}),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({})) as {detail?: string};
        throw new Error(payload.detail || "学校原版登录表单提交失败");
      }
      setHint("已提交学校原版登录表单，正在等待学校验证。此处不会将提交成功当作认证成功。");
      setShowRemote(true);
      requestFrame.current();
      void onConnected().catch(() => {});
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "学校登录暂时不可用");
    } finally {
      setPassword("");
      setSubmitting(false);
      pendingActions.current -= 1;
      requestFrame.current();
    }
  }

  function send(data: BrowserAction) {
    // Serialize keyboard and mouse actions so characters never arrive out of order.
    const generation = actionGeneration.current;
    pendingActions.current += 1;
    queue.current = queue.current.then(() => {
      if (generation !== actionGeneration.current) return;
      return post(data);
    }).catch(cause => {
      actionGeneration.current += 1;
      setError(cause instanceof Error ? cause.message : "学校登录操作失败");
    }).finally(() => {
      pendingActions.current -= 1;
      requestFrame.current();
    });
  }

  function flushText() {
    if (typingTimer.current !== null) window.clearTimeout(typingTimer.current);
    typingTimer.current = null;
    const text = textBuffer.current;
    textBuffer.current = "";
    if (text) send({action: "text", text});
  }

  useEffect(() => {
    if (!show) {
      setUsername("");
      setPassword("");
      setShowRemote(false);
      return;
    }
    setError("");
    setUsername("");
    setPassword("");
    setShowRemote(false);
    setHint("直接在下方输入学校账号；只有需要额外验证时再展开学校远程画面。");
    let checking = false;
    let active = true;
    const checker = window.setInterval(() => {
      if (checking) return;
      checking = true;
      void onConnected().then(ok => {
        if (!active) return;
        if (ok) { setHint("学校登录已经验证成功。"); onClose(); }
      }).catch(() => {}).finally(() => { checking = false; });
    }, 6000);
    return () => {
      active = false;
      actionGeneration.current += 1;
      window.clearInterval(checker);
      if (typingTimer.current !== null) window.clearTimeout(typingTimer.current);
      typingTimer.current = null;
      textBuffer.current = "";
    };
  }, [show, onClose, onConnected]);

  useEffect(() => {
    if (!show || !showRemote) return;
    let active = true;
    let currentUrl = "";
    let controller: AbortController | undefined;
    setFrameUrl("");
    setFrameError("");
    const pump = createFramePump({
      blocked: () => document.hidden || pendingActions.current > 0,
      schedule: (callback, delay) => window.setTimeout(callback, delay),
      cancel: timer => window.clearTimeout(timer),
      onError: () => setFrameError("学校画面暂时无法读取，正在重试；也可点击刷新画面。"),
      capture: async () => {
        controller = new AbortController();
        const deadline = window.setTimeout(() => controller?.abort(), 6000);
        let nextUrl = "";
        try {
          const response = await fetch(BASE + "frame", {
            credentials: "same-origin", cache: "no-store", signal: controller.signal,
          });
          if (!response.ok) throw new Error("frame unavailable");
          nextUrl = URL.createObjectURL(await response.blob());
          // Decode before replacing the visible image; retain the last good
          // frame during slow requests and failures instead of flashing black.
          const decoded = new Image();
          decoded.src = nextUrl;
          await decoded.decode();
          if (!active) return;
          const previous = currentUrl;
          currentUrl = nextUrl;
          nextUrl = "";
          setFrameUrl(currentUrl);
          setFrameError("");
          if (previous) URL.revokeObjectURL(previous);
        } finally {
          window.clearTimeout(deadline);
          if (nextUrl) URL.revokeObjectURL(nextUrl);
        }
      },
    });
    requestFrame.current = () => pump.request();
    const visible = () => { if (!document.hidden) pump.request(); };
    document.addEventListener("visibilitychange", visible);
    pump.request();
    return () => {
      active = false;
      pump.stop();
      controller?.abort();
      requestFrame.current = () => {};
      document.removeEventListener("visibilitychange", visible);
      if (currentUrl) URL.revokeObjectURL(currentUrl);
    };
  }, [show, showRemote]);

  if (!show) return null;

  function click(event: React.MouseEvent<HTMLImageElement>) {
    const img = image.current;
    if (!img) return;
    const point = browserImagePoint(
      event.clientX, event.clientY, img.getBoundingClientRect(),
      img.naturalWidth, img.naturalHeight,
    );
    if (!point) return;
    flushText();
    surface.current?.focus();
    setHint("正在将点击发送到学校浏览器…");
    send({action: "click", ...point});
  }

  function keyboard(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.nativeEvent.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
    const specials = ["Enter", "Tab", "Backspace", "Delete", "Escape",
      "ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"];
    if (specials.includes(event.key)) {
      event.preventDefault();
      flushText();
      send({action: "key", key: event.key});
    } else if (event.key.length === 1) {
      event.preventDefault();
      textBuffer.current += event.key;
      if (textBuffer.current.length >= 100) flushText();
      else {
        if (typingTimer.current !== null) window.clearTimeout(typingTimer.current);
        typingTimer.current = window.setTimeout(flushText, 90);
      }
    }
  }

  function paste(event: React.ClipboardEvent<HTMLDivElement>) {
    event.preventDefault();
    const value = event.clipboardData.getData("text").slice(0, 128);
    if (value && !/[\r\n\x00-\x1f]/.test(value)) {
      flushText();
      send({action: "text", text: value});
    }
  }

  return <div className="pmss-browser-backdrop" role="presentation">
    <section className="pmss-browser-modal" role="dialog" aria-modal="true"
      aria-label="学校原版 PMSS 登录">
      <div className="pmss-browser-heading">
        <div>
          <small><LockKeyhole size={13}/> SECURE SCHOOL SESSION</small>
          <h3>登录老师 PMSS 平台</h3>
          <p>仅管理员可操作 · 页面运行在受保护的服务器浏览器中，登录成功后全组共享连接状态</p>
        </div>
        <button type="button" aria-label="关闭登录窗口" onClick={onClose}><X size={20}/></button>
      </div>
      <form className="pmss-browser-quick-login" onSubmit={event => void loginSchool(event)}
        autoComplete="off" aria-label="学校 PMSS 即时登录">
        <div className="pmss-browser-quick-description">
          <LockKeyhole size={15}/> 学校账号快捷登录
          <span>本地即时输入，点击登录后一次性发送到受保护的学校浏览器，不保存密码。</span>
        </div>
        <div className="pmss-browser-quick-fields">
          <label>学校用户名
            <input name="school-username" type="text" autoComplete="off"
              value={username} onChange={event => setUsername(event.target.value)}
              maxLength={128} placeholder="输入学校用户名" required disabled={submitting}/>
          </label>
          <label>学校密码
            <input name="school-password" type="password" autoComplete="off"
              value={password} onChange={event => setPassword(event.target.value)}
              maxLength={256} placeholder="输入学校密码" required disabled={submitting}/>
          </label>
          <button type="submit" disabled={submitting || !username || !password}>
            {submitting ? "正在提交…" : "登录学校 PMSS"}
          </button>
        </div>
      </form>
      <button type="button" className="pmss-browser-toggle"
        aria-expanded={showRemote} onClick={() => setShowRemote(value => !value)}>
        {showRemote ? "收起学校原版画面" : "显示学校原版画面（验证码或额外验证时使用）"}
      </button>
      {showRemote && <div ref={surface} className="pmss-browser-surface" tabIndex={0}
        onKeyDown={keyboard} onPaste={paste} aria-label="学校网页登录画面与键盘控制">
        {frameUrl ? <img ref={image} draggable={false} alt="服务器学校官网登录页面"
          src={frameUrl} onClick={click}/>
          : <p role="status">正在读取学校登录画面…</p>}
      </div>}
      {showRemote && <div className="pmss-browser-footer">
        <span><Keyboard size={14}/> {hint}</span>
        <div className="pmss-browser-buttons">
          <button type="button" onClick={() => send({action: "scroll", dy: -1})}>向上</button>
          <button type="button" onClick={() => send({action: "scroll", dy: 1})}>向下</button>
          <button type="button" onClick={() => requestFrame.current()}>
            <RefreshCw size={14}/> 刷新画面</button>
          <button type="button" onClick={onClose}>完成 / 关闭</button>
        </div>
      </div>}
      {showRemote && <p className="pmss-browser-privacy">远程画面仅用于额外验证；建议优先使用上方原生输入框，避免逐字远程操作。</p>}
      {error && <p className="pmss-browser-error" role="alert">{error}</p>}
      {frameError && <p className="pmss-browser-error" role="status">{frameError}</p>}
      <p className="pmss-browser-privacy"><ExternalLink size={13}/> 账号信息仅用于本次学校网页登录，经过当前 HTTPS 连接传送到受保护服务器，不写入账户数据库。
        登录后的报价提交与原版出清仍须分别人工确认；不会开放服务器桌面或自动提交报价。</p>
    </section>
  </div>;
}
