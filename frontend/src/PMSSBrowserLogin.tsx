import { useEffect, useRef, useState } from "react";
import { ExternalLink, Keyboard, LockKeyhole, RefreshCw, X } from "lucide-react";
import "./pmss-school-login.css";

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
  const [error, setError] = useState("");
  const [hint, setHint] = useState("点击画面里的输入框，然后在键盘上正常输入。");
  const image = useRef<HTMLImageElement>(null);
  const surface = useRef<HTMLDivElement>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());

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
    setFrame(n => n + 1);
  }

  function send(data: BrowserAction) {
    // Serialize keyboard and mouse actions so characters never arrive out of order.
    queue.current = queue.current.then(() => post(data)).catch(cause => {
      setError(cause instanceof Error ? cause.message : "学校登录操作失败");
    });
  }

  useEffect(() => {
    if (!show) return;
    setError("");
    setHint("请在上方的学校原版页面完成身份验证。无需将密码交给 PowerBid 管理员。");
    void post({action: "open"}).catch(e => setError(String(e)));
    const images = window.setInterval(() => setFrame(n => n + 1), 1800);
    const checker = window.setInterval(() => {
      void onConnected().then(ok => {
        if (ok) { setHint("学校登录已经验证成功。"); onClose(); }
      });
    }, 6000);
    return () => { window.clearInterval(images); window.clearInterval(checker); };
  }, [show, onClose, onConnected]);

  if (!show) return null;

  function click(event: React.MouseEvent<HTMLImageElement>) {
    const img = image.current;
    if (!img) return;
    const rect = img.getBoundingClientRect();
    const x = (event.clientX - rect.left) * img.naturalWidth / rect.width;
    const y = (event.clientY - rect.top) * img.naturalHeight / rect.height;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    surface.current?.focus();
    send({action: "click", x: Math.round(x), y: Math.round(y)});
  }

  function keyboard(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.nativeEvent.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
    const specials = ["Enter", "Tab", "Backspace", "Delete", "Escape",
      "ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"];
    if (specials.includes(event.key)) {
      event.preventDefault();
      send({action: "key", key: event.key});
    } else if (event.key.length === 1) {
      event.preventDefault();
      send({action: "text", text: event.key});
    }
  }

  function paste(event: React.ClipboardEvent<HTMLDivElement>) {
    event.preventDefault();
    const value = event.clipboardData.getData("text").slice(0, 128);
    if (value && !/[\r\n\x00-\x1f]/.test(value)) send({action: "text", text: value});
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
      <div ref={surface} className="pmss-browser-surface" tabIndex={0}
        onKeyDown={keyboard} onPaste={paste} aria-label="学校网页登录画面与键盘控制">
        <img ref={image} draggable={false} alt="服务器学校官网登录页面"
          src={BASE + "frame?seq=" + frame} onClick={click}
          onError={() => setError("暂时无法读取学校浏览器画面，请检查管理员登录网关")}
        />
      </div>
      <div className="pmss-browser-footer">
        <span><Keyboard size={14}/> {hint}</span>
        <div className="pmss-browser-buttons">
          <button type="button" onClick={() => send({action: "scroll", dy: -1})}>向上</button>
          <button type="button" onClick={() => send({action: "scroll", dy: 1})}>向下</button>
          <button type="button" onClick={() => setFrame(n => n + 1)}>
            <RefreshCw size={14}/> 刷新画面</button>
          <button type="button" onClick={onClose}>完成 / 关闭</button>
        </div>
      </div>
      {error && <p className="pmss-browser-error" role="alert">{error}</p>}
      <p className="pmss-browser-privacy"><ExternalLink size={13}/> 仅用于学校网页登录。
        登录后的报价提交与原版出清仍须分别人工确认；不会开放服务器桌面或自动提交报价。</p>
    </section>
  </div>;
}
