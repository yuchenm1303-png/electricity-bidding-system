import { useEffect, useRef, useState } from "react";
import { ShieldCheck } from "lucide-react";

type TurnstileApi = {
  render: (element: HTMLElement, config: {
    sitekey: string;
    theme: "dark";
    callback: (token: string) => void;
    "expired-callback": () => void;
    "error-callback": () => void;
  }) => string;
  remove: (widget: string) => void;
};
declare global {
  interface Window { turnstile?: TurnstileApi }
}
let scriptReady: Promise<void> | undefined;

function loadScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve();
  if (!scriptReady) {
    scriptReady = new Promise<void>((resolve, reject) => {
      const node = document.createElement("script");
      node.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      node.async = true;
      node.onload = () => resolve();
      node.onerror = () => { scriptReady = undefined; reject(new Error("无法加载验证服务")); };
      document.head.appendChild(node);
    });
  }
  return scriptReady;
}

export default function TurnstileWidget({
  siteKey, onChange, resetKey,
}: { siteKey: string; onChange: (value: string) => void; resetKey: number }) {
  const root = useRef<HTMLDivElement>(null);
  const update = useRef(onChange);
  const [message, setMessage] = useState("正在加载安全验证…");
  useEffect(() => { update.current = onChange; }, [onChange]);
  useEffect(() => {
    if (!siteKey) return;
    let active = true;
    let widget: string | undefined;
    update.current("");
    setMessage("正在加载安全验证…");
    void loadScript().then(() => {
      if (!active || !root.current || !window.turnstile) return;
      widget = window.turnstile.render(root.current, {
        sitekey: siteKey,
        theme: "dark",
        callback: (token) => { if (active) { update.current(token); setMessage(""); } },
        "expired-callback": () => { if (active) { update.current(""); setMessage("验证已过期，请重新验证"); } },
        "error-callback": () => { if (active) { update.current(""); setMessage("验证加载失败，请刷新后重试"); } },
      });
      setMessage("");
    }).catch(() => { if (active) setMessage("验证服务连接失败，请刷新页面重试"); });
    return () => {
      active = false;
      update.current("");
      if (widget) window.turnstile?.remove(widget);
    };
  }, [siteKey, resetKey]);
  if (!siteKey) return null;
  return <div className="pb-social-captcha" aria-label="人机验证">
    <div className="pb-social-captcha-title"><ShieldCheck size={15}/> 安全验证</div>
    <div ref={root} className="pb-social-captcha-widget"/>
    {message && <span className="pb-social-note" role="status">{message}</span>}
  </div>;
}
