import { useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, Eye, EyeOff, Fingerprint, KeyRound, LockKeyhole, Mail, ShieldCheck, UserRound } from "lucide-react";
import smirelLogo from "./assets/smirel-logo.png";
import "./account.css";

const base = import.meta.env.BASE_URL;

export default function AdminActivation() {
  const [token] = useState(() => window.location.hash.slice(1));
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    // Fragment never goes to the server; erase it from the browser history too.
    if (window.location.hash) window.history.replaceState(null, "", base + "setup-admin");
    document.title = "初始化管理员 · PowerBid";
  }, []);
  const valid = token.length >= 32 && password.length >= 12 && password === confirm;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (working || !valid) return;
    setWorking(true);
    setError("");
    try {
      const response = await fetch(base + "api/auth/setup-admin", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-PowerBid-Request": "1" },
        body: JSON.stringify({ username: username.trim(), email: email.trim(), password, invite: token }),
      });
      const data = await response.json().catch(()=>({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "管理员初始化失败");
      setPassword("");
      setConfirm("");
      window.location.replace(base + "app");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法完成账号激活");
      setWorking(false);
    }
  };
  return <main className="pb-identity-screen">
    <div className="pb-identity-grain" aria-hidden="true"/>
    <div className="pb-identity-layout">
      <aside className="pb-identity-story">
        <a className="pb-identity-brand" href={base}>
          <img src={smirelLogo} alt="Smirel" width={94} height={31}/>
          <span className="pb-identity-brand-divider"/><strong>PowerBid</strong>
        </a>
        <div className="pb-identity-story-content">
          <span className="pb-identity-eyebrow"><span/> POWERBID / ADMINISTRATION</span>
          <h1>建立身份，<br/><em>开启研究。</em></h1>
          <p>设置你的独立管理员账号。<br/>随后即可管理成员访问与电力报价工作台。</p>
          <div className="pb-identity-network" aria-hidden="true">
            <svg viewBox="0 0 510 210" fill="none" role="presentation">
              <path d="M18 141L104 75L197 119L284 43L389 90L485 27M18 141L148 187L197 119L389 90L446 179M104 75L284 43L446 179L485 27" stroke="currentColor" strokeWidth="1.1" strokeOpacity=".42"/>
              {[ [18,141],[104,75],[197,119],[284,43],[389,90],[485,27],[148,187],[446,179] ].map(([x,y],i)=><g key={i}>
                <circle cx={x} cy={y} r={i===3?8:5} fill="#6678E9" opacity=".17"/>
                <circle cx={x} cy={y} r={i===3?3.8:2.6} fill="#B5C3FF"/>
              </g>)}
            </svg>
          </div>
        </div>
        <div className="pb-identity-story-footer"><span>电力报价系统 · 管理员初始化</span><span>ONE-TIME ACTIVATION</span></div>
      </aside>
      <section className="pb-identity-access">
        <div className="pb-identity-access-top">
          <a className="pb-identity-back" href={base}><ArrowLeft size={15}/> 返回首页</a>
          <span className="pb-identity-access-tag"><span/> SECURE SETUP</span>
        </div>
        <div className="pb-identity-access-center">
          <div className="pb-identity-card">
            <div className="pb-identity-emblem"><Fingerprint size={27} strokeWidth={1.5}/></div>
            <span className="pb-identity-kicker">FIRST ADMINISTRATOR</span>
            <h2>初始化管理员</h2>
            <p className="pb-identity-lead">这是一条仅可使用一次的激活链接。请设置你自己的登录信息。</p>
            {!token && <div className="pb-identity-unavailable" role="alert">
              <KeyRound size={17}/>缺少一次性激活凭证。请使用专属邀请链接，不要直接打开这个地址。
            </div>}
            <form className="pb-identity-form" onSubmit={submit}>
              <div className="pb-identity-field"><label htmlFor="activate-username">管理员用户名</label>
                <div className="pb-identity-input-wrap"><UserRound size={17}/><input id="activate-username"
                  required pattern="[A-Za-z][A-Za-z0-9_-]{2,31}" minLength={3} maxLength={32}
                  autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)}
                  placeholder="如 poweradmin"/></div></div>
              <div className="pb-identity-field"><label htmlFor="activate-email">电子邮箱</label>
                <div className="pb-identity-input-wrap"><Mail size={17}/><input id="activate-email" required type="email"
                  autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)}
                  placeholder="你的邮箱"/></div></div>
              <div className="pb-identity-field"><label htmlFor="activate-password">设置密码</label>
                <div className="pb-identity-input-wrap"><LockKeyhole size={17}/><input id="activate-password"
                  required type={showPassword?"text":"password"} minLength={12} maxLength={128}
                  autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)}
                  placeholder="至少 12 位字符"/>
                  <button type="button" className="pb-identity-eye" onClick={()=>setShowPassword(v=>!v)}
                    aria-label={showPassword?"隐藏密码":"显示密码"}>{showPassword?<EyeOff size={17}/>:<Eye size={17}/>}</button>
                </div></div>
              <div className="pb-identity-field"><label htmlFor="activate-confirm">确认密码</label>
                <div className="pb-identity-input-wrap"><ShieldCheck size={17}/><input id="activate-confirm"
                  required type={showPassword?"text":"password"} minLength={12} maxLength={128}
                  autoComplete="new-password" value={confirm} onChange={e=>setConfirm(e.target.value)}
                  placeholder="重新输入一次密码"/></div>
                {confirm && password !== confirm && <span className="pb-identity-field-note">两次输入的密码不一致。</span>}
              </div>
              {error && <div className="pb-identity-error" role="alert">{error}</div>}
              <button className="pb-identity-primary" type="submit" disabled={!valid||working}>
                {working?"正在激活…":"激活管理员账号"}
                {working?<span className="pb-identity-spinner"/>:<ArrowRight size={18}/>}
              </button>
            </form>
            <div className="pb-identity-card-bottom"><span><CheckCircle2 size={15}/>
              激活完成后自动进入工作台，一次性邀请立即失效。</span></div>
          </div>
        </div>
        <footer className="pb-identity-access-footer"><ShieldCheck size={14}/> HTTPS 安全连接 · 不会在服务器保存明文密码</footer>
      </section>
    </div>
  </main>;
}
