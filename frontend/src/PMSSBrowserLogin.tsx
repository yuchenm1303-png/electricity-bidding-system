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
  const [error, setError] = useState("");
  const [hint, setHint] = useState("点击画面里的输入框，然后在键盘上正常输入。");
  const image = useRef<HTMLImageElement>(null);
  const keyboardSink = useRef<HTMLInputElement>(null);
  const composing = useRef(false);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const textBuffer = useRef("");
  const typingTimer = useRef<number | null>(null);
  const lastInteraction = useRef(0);

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
    if (data.action === "text") setHint("已将键盘输入同步到学校页面，画面正在更新。");
    if (data.action === "open" || data.action === "text" || data.action === "key") {
      setFrame(n => n + 1);
    }
  }

  function send(data: BrowserAction) {
    // Serialize keyboard and mouse actions so characters never arrive out of order.
    queue.current = queue.current.then(() => post(data)).catch(cause => {
      setError(cause instanceof Error ? cause.message : "学校登录操作失败");
    });
  }

  function acceptText(value: string) {
    if (!value || /[\u0000-\u001f]/.test(value)) return;
    lastInteraction.current = Date.now();
    textBuffer.current += value;
    if (textBuffer.current.length >= 100) flushText();
    else {
      if (typingTimer.current !== null) window.clearTimeout(typingTimer.current);
      typingTimer.current = window.setTimeout(flushText, 90);
    }
  }

  function flushText() {
    if (typingTimer.current !== null) window.clearTimeout(typingTimer.current);
    typingTimer.current = null;
    const text = textBuffer.current;
    textBuffer.current = "";
    if (text) {
      for (let offset = 0; offset < text.length; offset += 100) {
        send({action: "text", text: text.slice(offset, offset + 100)});
      }
    }
  }

  useEffect(() => {
    if (!show) return;
    setError("");
    setHint("请在上方的学校原版页面完成身份验证。无需将密码交给 PowerBid 管理员。");
    void post({action: "open"}).catch(e => setError(String(e)));
    const images = window.setInterval(() => {
      if (Date.now() - lastInteraction.current > 6500) setFrame(n => n + 1);
    }, 4500);
    const checker = window.setInterval(() => {
      void onConnected().then(ok => {
        if (ok) { setHint("学校登录已经验证成功。"); onClose(); }
      });
    }, 6000);
    return () => {
      window.clearInterval(images); window.clearInterval(checker);
      if (typingTimer.current !== null) window.clearTimeout(typingTimer.current);
      typingTimer.current = null;
      textBuffer.current = "";
    };
  }, [show, onClose, onConnected]);

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
    // A real native input keeps browser keyboard focus even across React rerenders.
    keyboardSink.current?.focus({ preventScroll: true });
    lastInteraction.current = Date.now();
    setHint("正在将点击发送到学校浏览器…");
    send({action: "click", ...point});
  }

  function keyboard(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing || composing.current) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      flushText();
      send({action: "key", key: "SelectAll"});
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const specials = ["Enter", "Tab", "Backspace", "Delete", "Escape",
      "ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"];
    if (specials.includes(event.key)) {
      event.preventDefault();
      flushText();
      send({action: "key", key: event.key});
    }
    // Ordinary characters are delivered by the native input event, not keydown.
  }

  function nativeInput(event: React.FormEvent<HTMLInputElement>) {
    if (composing.current) return;
    const element = event.currentTarget;
    const value = element.value;
    element.value = ""; // No passwords or account names retained in the input DOM.
    acceptText(value);
  }

  function compositionEnd(event: React.CompositionEvent<HTMLInputElement>) {
    composing.current = false;
    const element = event.currentTarget;
    const value = element.value;
    element.value = "";
    acceptText(value);
  }

  function paste(event: React.ClipboardEvent<HTMLInputElement>) {
    event.preventDefault();
    const value = event.clipboardData.getData("text").slice(0, 128);
    acceptText(value);
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
      <div className="pmss-browser-surface" aria-label="学校网页登录画面">
        <img ref={image} draggable={false} alt="服务器学校官网登录页面"
          src={BASE + "frame?seq=" + frame} onClick={click}
          onError={() => setError("暂时无法读取学校浏览器画面，请检查管理员登录网关")}
        />
      </div>
      <div className="pmss-browser-native-input">
        <label htmlFor="pmss-native-input"><Keyboard size={15}/> 键盘输入</label>
        <input id="pmss-native-input" ref={keyboardSink} type="password"
          autoComplete="off" autoCorrect="off" spellCheck={false}
          aria-label="输入到学校网页当前选中的账号或密码框"
          placeholder="先点击上方学校输入框，再直接在这里键入"
          onKeyDown={keyboard} onInput={nativeInput} onPaste={paste}
          onCompositionStart={() => { composing.current = true; }}
          onCompositionEnd={compositionEnd}
        />
        <span>即时转发，不保存输入内容</span>
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
