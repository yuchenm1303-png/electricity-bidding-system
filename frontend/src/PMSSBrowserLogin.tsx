import { useEffect, useRef, useState } from "react";
import { ExternalLink, Keyboard, LockKeyhole, RefreshCw, X } from "lucide-react";
import "./pmss-school-login.css";
import { browserImagePoint } from "./pmssBrowserCoordinates";

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
  const [frame, setFrame] = useState(0);
  const [showRemote, setShowRemote] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [hint, setHint] = useState("点击画面里的输入框，然后在键盘上正常输入。");
  const image = useRef<HTMLImageElement>(null);
  const surface = useRef<HTMLDivElement>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const textBuffer = useRef("");
  const typingTimer = useRef<number | null>(null);
  const lastInteraction = useRef(0);
  const framePending = useRef(false);

  async function post(data: BrowserAction): Promise<void> {
    const response = await fetch(BASE + "action", {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-PowerBid-Request": "1" },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
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
    lastInteraction.current = Date.now();
    if (data.action === "open" || data.action === "key" && data.key === "Enter") {
      setFrame(n => n + 1);
    }
  }

  async function loginSchool(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || !username || !password) return;
    setSubmitting(true);
    setError("");
    setHint("正在将账号信息一次性提交到学校原版登录页面…");
    try {
      // One request for the complete school form, not one round trip per key.
      const response = await fetch(BASE + "login", {
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
      setFrame(n => n + 1);
      void onConnected();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "学校登录暂时不可用");
    } finally {
      setPassword("");
      setSubmitting(false);
    }
  }

  function send(data: BrowserAction) {
    // Serialize keyboard and mouse actions so characters never arrive out of order.
    queue.current = queue.current.then(() => post(data)).catch(cause => {
      setError(cause instanceof Error ? cause.message : "学校登录操作失败");
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
    const checker = window.setInterval(() => {
      void onConnected().then(ok => {
        if (ok) { setHint("学校登录已经验证成功。"); onClose(); }
      }).catch(() => {});
    }, 6000);
    return () => {
      window.clearInterval(checker);
      if (typingTimer.current !== null) window.clearTimeout(typingTimer.current);
      typingTimer.current = null;
      textBuffer.current = "";
    };
  }, [show, onClose, onConnected]);

  useEffect(() => {
    if (!show || !showRemote) { framePending.current = false; return; }
    // Remote screen is an optional fallback. No image polling while the
    // administrator types in native browser inputs.
    const refresh = () => {
      if (document.hidden || framePending.current ||
          Date.now() - lastInteraction.current <= 2500) return;
      framePending.current = true;
      setFrame(n => n + 1);
      // Resume only after img load/error, never queue screenshots.
    };
    const timer = window.setInterval(refresh, 4500);
    return () => {window.clearInterval(timer);};
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
    lastInteraction.current = Date.now();
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
      lastInteraction.current = Date.now();
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
        aria-expanded={showRemote} onClick={() => {setShowRemote(value => !value);setFrame(n => n + 1);}}>
        {showRemote ? "收起学校原版画面" : "显示学校原版画面（验证码或额外验证时使用）"}
      </button>
      {showRemote && <div ref={surface} className="pmss-browser-surface" tabIndex={0}
        onKeyDown={keyboard} onPaste={paste} aria-label="学校网页登录画面与键盘控制">
        <img ref={image} draggable={false} alt="服务器学校官网登录页面"
          src={BASE + "frame?seq=" + frame} onClick={click}
          onLoad={() => { framePending.current = false; }}
          onError={() => { framePending.current = false; setError("暂时无法读取学校浏览器画面，请检查管理员登录网关"); }}
        />
      </div>}
      {showRemote && <div className="pmss-browser-footer">
        <span><Keyboard size={14}/> {hint}</span>
        <div className="pmss-browser-buttons">
          <button type="button" onClick={() => send({action: "scroll", dy: -1})}>向上</button>
          <button type="button" onClick={() => send({action: "scroll", dy: 1})}>向下</button>
          <button type="button" onClick={() => setFrame(n => n + 1)}>
            <RefreshCw size={14}/> 刷新画面</button>
          <button type="button" onClick={onClose}>完成 / 关闭</button>
        </div>
      </div>}
      {showRemote && <p className="pmss-browser-privacy">远程画面仅用于额外验证；建议优先使用上方原生输入框，避免逐字远程操作。</p>}
      {error && <p className="pmss-browser-error" role="alert">{error}</p>}
      <p className="pmss-browser-privacy"><ExternalLink size={13}/> 账号信息仅用于本次学校网页登录，经过当前 HTTPS 连接传送到受保护服务器，不写入账户数据库。
        登录后的报价提交与原版出清仍须分别人工确认；不会开放服务器桌面或自动提交报价。</p>
    </section>
  </div>;
}
