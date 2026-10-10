import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  Activity, ArrowLeft, ArrowRight, ArrowUpRight, Check, CheckCircle2,
  ChevronRight, Eye, EyeOff, Fingerprint, Github, LockKeyhole, Mail,
  Search, Shield, ShieldCheck, UserRound, Users,
  UserX, X,
} from "lucide-react";
import smirelLogo from "./assets/smirel-logo.png";
import AdminActivation from "./AdminActivation";
import TurnstileWidget from "./TurnstileWidget";
import Workspace from "./WorkspaceEntry";
import "./account.css";
import "./account-portal-polish.css";
import "./account-buttons.css";
import "./icon-interactions.css";
import "./account-one-screen.css";
import "./account-premium.css";

export type AccountUser = {
  id: number;
  username: string;
  email: string;
  role: "admin" | "member";
  active: boolean;
  created_at?: number;
};
type AuthConfig = {
  enabled: boolean;
  registration_open: boolean;
  turnstile_site_key?: string;
  social?: { google: boolean; github: boolean };
};
type AuthView = "login" | "register";
type UserFilter = "all" | "active" | "disabled";
const base = import.meta.env.BASE_URL;

async function request<T>(path: string, method = "GET", data?: unknown): Promise<T> {
  const response = await fetch(base + "api/auth/" + path, {
    method,
    credentials: "same-origin",
    headers: {
      "X-PowerBid-Request": "1",
      ...(data === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof result.detail === "string" ? result.detail : "网络出现问题，请稍后重试");
  }
  return result as T;
}

function Monogram({ name, size = "regular" }: { name: string; size?: "regular" | "large" }) {
  return <span className={"pb-identity-avatar " + (size === "large" ? "is-large" : "")}
    aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>;
}

function CloseButton({ close }: { close: () => void }) {
  return <button className="pb-identity-close" type="button" onClick={close} aria-label="关闭">
    <X size={19}/>
  </button>;
}

function useDialogEscape(close: () => void) {
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [close]);
}

function AuthScene({ config, onReady }: { config: AuthConfig; onReady: (user: AccountUser) => void }) {
  const [view, setView] = useState<AuthView>(() => window.location.pathname.endsWith("/register") ? "register" : "login");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [capsLock, setCapsLock] = useState(false);
  const [captcha, setCaptcha] = useState("");
  const [resetCaptcha, setResetCaptcha] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);
  const previousCardHeightRef = useRef<number | null>(null);
  const cardHeightAnimationRef = useRef<Animation | null>(null);
  const oauthError = new URLSearchParams(window.location.search).get("auth_error");
  const oauthMessage = oauthError === "existing_email"
    ? "这个邮箱已有 PowerBid 账号。为保护账号安全，请先使用原来的登录方式，暂不自动合并账号。"
    : oauthError === "forbidden" ? "当前账号无法通过此方式登录，或管理员尚未开放注册。"
    : oauthError ? "第三方登录未完成，请重新尝试或使用密码登录。" : "";
  const isRegister = view === "register";
  const authAvailable = config.enabled && (!isRegister || config.registration_open);
  // Record the visible height before React swaps the form fields. The next
  // layout effect measures the new natural height and animates between them.
  useLayoutEffect(() => {
    const card = cardRef.current;
    const fromHeight = previousCardHeightRef.current;
    previousCardHeightRef.current = null;
    if (!card || fromHeight === null || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const toHeight = card.getBoundingClientRect().height;
    if (Math.abs(toHeight - fromHeight) > 1) {
      card.style.overflow = "clip";
      const animation = card.animate(
        [{ height: `${fromHeight}px` }, { height: `${toHeight}px` }],
        { duration: 460, easing: "cubic-bezier(.22, 1, .36, 1)" }
      );
      cardHeightAnimationRef.current = animation;
      const finish = () => {
        if (cardHeightAnimationRef.current !== animation) return;
        cardHeightAnimationRef.current = null;
        card.style.overflow = "";
      };
      animation.addEventListener("finish", finish, { once: true });
      animation.addEventListener("cancel", finish, { once: true });
    }

    const content = card.querySelector<HTMLElement>(".pb-identity-form");
    content?.animate(
      [{ opacity: 0.45, transform: "translateY(7px)" }, { opacity: 1, transform: "translateY(0)" }],
      { duration: 350, easing: "cubic-bezier(.22, 1, .36, 1)" }
    );
  }, [view]);

  const switchView = (next: AuthView) => {
    if (next === view) return;
    previousCardHeightRef.current = cardRef.current?.getBoundingClientRect().height ?? null;
    cardHeightAnimationRef.current?.cancel();
    setView(next);
    setCaptcha("");
    setResetCaptcha(v => v + 1);
    window.history.replaceState(null, "", base + (next === "register" ? "register" : "login"));
    setPassword("");
    setShowPassword(false);
    setError("");
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    if (!authAvailable) {
      setError(config.enabled ? "注册暂未开放，请联系管理员。" : "账号系统尚未启用，暂时无法注册或登录。");
      return;
    }
    if (config.turnstile_site_key && !captcha) {
      setError("请先完成人机验证。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = isRegister ?
        { username: username.trim(), email: email.trim(), password, turnstile_token: captcha || undefined } :
        { username: username.trim(), password, turnstile_token: captcha || undefined };
      const user = await request<AccountUser>(isRegister ? "register" : "login", "POST", body);
      setPassword("");
      window.history.replaceState(null, "", base + "app");
      onReady(user);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "暂时无法连接到账号服务");
      setCaptcha("");
      setResetCaptcha(v => v + 1);
    } finally {
      setBusy(false);
    }
  };
  return <main className="pb-identity-screen" data-auth-view={isRegister ? "register" : "login"}>
    <div className="pb-identity-grain" aria-hidden="true"/>
    <div className="pb-identity-layout">
      <aside className="pb-identity-story">
        <a className="pb-identity-brand" href={base} aria-label="Smirel PowerBid 首页">
          <img src={smirelLogo} alt="Smirel" width={94} height={31}/>
          <span className="pb-identity-brand-divider"/>
          <strong>PowerBid</strong>
        </a>
        <div className="pb-identity-story-content">
          <span className="pb-identity-eyebrow"><span/> POWER MARKET INTELLIGENCE</span>
          <h1>让每一次报价，<br/><em>都有迹可循。</em></h1>
          <p>从电力市场仿真到策略分析，<br/>在同一个空间，连接数据与决策。</p>
          <div className="pb-identity-network" aria-hidden="true">
            <div className="pb-identity-network-heading">
              <span>GRID <i/> OVERVIEW</span>
              <small>NETWORK MODEL</small>
            </div>
            <svg className="pb-identity-network-graph" viewBox="0 0 560 180" fill="none" role="presentation">
              <path className="pb-network-trace" d="M38 120L139 63L240 112L343 38L439 88L528 53M38 120L192 155L240 112L478 149L528 53M139 63L343 38L478 149M240 112L439 88L478 149"/>
              <path className="pb-network-highlight" d="M38 120L139 63L240 112L343 38L439 88L528 53"/>
              {[[38,120],[139,63],[240,112],[343,38],[439,88],[528,53],[192,155],[478,149]].map(([x,y],i)=>
                <g key={i} className="pb-network-point">
                  <circle cx={x} cy={y} r={i===3?5:3.5} className="pb-network-point-shell"/>
                  <circle cx={x} cy={y} r={i===3?2.4:1.7} className="pb-network-point-core"/>
                </g>)}
            </svg>
            <div className="pb-identity-network-footer">电力网络拓扑示意 <span>·</span> 非实时数据</div>
          </div>
          <div className="pb-identity-story-trails" aria-label="研究流程">
            <span><i>01</i> 数据洞察</span>
            <span><i>02</i> 策略推演</span>
            <span><i>03</i> 情景评估</span>
          </div>
        </div>
        <div className="pb-identity-story-footer"><span>电力报价系统 · 小组作业</span><span>EST. 2026 <span className="pb-identity-footer-dot"/> SYSTEM ONLINE</span></div>
      </aside>

      <section className="pb-identity-access" aria-label="账号访问">
        <div className="pb-identity-access-top">
          <a href={base} className="pb-identity-back"><ArrowLeft size={15}/> 返回首页</a>
          <span className="pb-identity-access-tag"><span/> SECURE ACCESS</span>
        </div>
        <div className="pb-identity-access-center">
          <div className="pb-identity-card" ref={cardRef}>
            <div className="pb-identity-emblem"><Fingerprint size={27} strokeWidth={1.5}/></div>
            <span className="pb-identity-kicker">YOUR WORKSPACE</span>
            <h2>{isRegister ? "创建 PowerBid 账号" : "欢迎回来"}</h2>
            <p className="pb-identity-lead">{isRegister ? "只需简单几步，即可开始你的策略研究。" : "登录，继续你的电力市场探索。"}</p>
            <div className="pb-identity-tabs" role="group" aria-label="登录或注册" data-view={view}>
                <button type="button" className={!isRegister ? "selected" : ""} aria-pressed={!isRegister} onClick={()=>switchView("login")}>登录账号</button>
                <button type="button" className={isRegister ? "selected" : ""} aria-pressed={isRegister} onClick={()=>switchView("register")}>创建账号</button>
              </div>
            {!config.enabled &&
              <div className="pb-identity-unavailable" role="status">
                <ShieldCheck size={17}/> 账号系统正在配置中。你可以预览登录和注册页面，暂时还不能提交账号信息。
              </div>}
            {config.enabled && !config.registration_open && isRegister &&
              <div className="pb-identity-unavailable" role="status">
                <ShieldCheck size={17}/> 注册暂未开放。如需账号，请联系管理员。
              </div>}
            {oauthMessage && <div className="pb-identity-error" role="alert"><Shield size={16}/>{oauthMessage}</div>}
            <form className="pb-identity-form" onSubmit={submit}>
              <div className="pb-identity-field">
                <label htmlFor="auth-name">用户名</label>
                <div className="pb-identity-input-wrap">
                  <UserRound size={17}/>
                  <input id="auth-name" required minLength={3} maxLength={32} pattern="[A-Za-z][A-Za-z0-9_-]{2,31}"
                    autoComplete="username" placeholder="你的用户名" value={username} onChange={e=>setUsername(e.target.value)}/>
                </div>
              </div>
              {isRegister && <div className="pb-identity-field">
                <label htmlFor="auth-email">电子邮箱</label>
                <div className="pb-identity-input-wrap">
                  <Mail size={17}/>
                  <input id="auth-email" type="email" autoComplete="email" required placeholder="name@example.com"
                    value={email} onChange={e=>setEmail(e.target.value)}/>
                </div>
              </div>}
              <div className="pb-identity-field">
                <label htmlFor="auth-password">密码</label>
                <div className="pb-identity-input-wrap">
                  <LockKeyhole size={17}/>
                  <input id="auth-password" type={showPassword?"text":"password"} required minLength={12} maxLength={128}
                    autoComplete={isRegister?"new-password":"current-password"} placeholder="至少 12 位字符"
                    value={password} onChange={e=>setPassword(e.target.value)}
                    onKeyUp={e=>setCapsLock(e.getModifierState("CapsLock"))}/>
                  <button type="button" className="pb-identity-eye" aria-label={showPassword?"隐藏密码":"显示密码"}
                    onClick={()=>setShowPassword(v=>!v)}>{showPassword?<EyeOff size={17}/>:<Eye size={17}/>}</button>
                </div>
                {capsLock&&<span className="pb-identity-field-note">Caps Lock 已开启</span>}
                {isRegister&&<>
                  <div className="pb-pass-progress" aria-hidden="true">
                    {[3,6,9,12].map(length=><span key={length} className={password.length>=length?"is-filled":""}/>)}
                  </div>
                  <div className="pb-pass-progress-label"><span>密码长度至少 12 位</span><strong>{Math.min(password.length,128)} / 12</strong></div>
                </>}
              </div>
              {config.turnstile_site_key && <TurnstileWidget
                siteKey={config.turnstile_site_key} onChange={setCaptcha} resetKey={resetCaptcha}/>}
              {error&&<div className="pb-identity-error" role="alert"><Shield size={16}/>{error}</div>}
              <button className="pb-identity-primary" type="submit" disabled={busy || !authAvailable}>
                <span>{!authAvailable?"暂未开放":busy?"正在验证…":isRegister?"创建账号":"进入工作台"}</span>
                {busy?<span className="pb-identity-spinner"/>:<ArrowRight size={18}/>}
              </button>
            </form>
            {config.enabled && <div className="pb-social-auth">
              <div className="pb-social-divider"><span/>或者使用以下方式继续<span/></div>
              <div className="pb-social-options">
                <a className={"pb-social-button"+(!config.social?.google?" is-disabled":"")}
                  aria-disabled={!config.social?.google}
                  href={config.social?.google ? base+"api/auth/oauth/google/start" : undefined}
                  title={config.social?.google?"使用 Google 登录":"Google 登录尚未配置"}>
                  <span className="pb-google-mark" aria-hidden="true">G</span> Google
                  {!config.social?.google && <small>待配置</small>}
                </a>
                <a className={"pb-social-button"+(!config.social?.github?" is-disabled":"")}
                  aria-disabled={!config.social?.github}
                  href={config.social?.github ? base+"api/auth/oauth/github/start" : undefined}
                  title={config.social?.github?"使用 GitHub 登录":"GitHub 登录尚未配置"}>
                  <Github size={19} aria-hidden="true"/> GitHub
                  {!config.social?.github && <small>待配置</small>}
                </a>
              </div>
              <div className="pb-social-note">使用第三方账号登录不会自动关联已有同邮箱账号。</div>
            </div>}
            <div className="pb-identity-card-bottom">
              {!config.enabled
                ? <a className="pb-identity-demo-link" href={base+"app"}>先进入演示工作台 <ArrowUpRight size={15}/></a>
                : <span>{isRegister?"已有账号？":config.registration_open?"还没有账号？":"当前仅支持已开通的账号登录。"}
                    <button type="button" onClick={()=>switchView(isRegister?"login":"register")}>{isRegister?"返回登录":"查看注册"}<ChevronRight size={13}/></button>
                  </span>}
            </div>
          </div>
        </div>
        <footer className="pb-identity-access-footer"><ShieldCheck size={14}/> 安全连接 · 仅用于教学与研究</footer>
      </section>
    </div>
  </main>;
}

function ProfilePanel({ user, close }: { user: AccountUser; close: () => void }) {
  useDialogEscape(close);
  const date = user.created_at ? new Date(user.created_at * 1000).toLocaleDateString("zh-CN") : "暂无记录";
  return <div className="pb-identity-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)close();}}>
    <section className="pb-identity-modal pb-identity-profile" role="dialog" aria-modal="true" aria-labelledby="pb-profile-title">
      <header className="pb-identity-modal-header">
        <div><span className="pb-identity-kicker">ACCOUNT OVERVIEW</span><h2 id="pb-profile-title">个人资料</h2></div>
        <CloseButton close={close}/>
      </header>
      <div className="pb-identity-profile-hero">
        <Monogram name={user.username} size="large"/>
        <div><h3>{user.username}</h3><p>{user.role==="admin"?"系统管理员":"普通用户"} <span>·</span> {user.active?"账号正常":"账号已禁用"}</p></div>
        <span className="pb-identity-profile-verified"><CheckCircle2 size={15}/> 已登录</span>
      </div>
      <div className="pb-identity-section-caption">ACCOUNT DETAILS</div>
      <div className="pb-identity-details">
        <div><span><UserRound size={16}/> 用户名</span><strong>{user.username}</strong></div>
        <div><span><Mail size={16}/> 电子邮箱</span><strong>{user.email}</strong></div>
        <div><span><ShieldCheck size={16}/> 账号角色</span><strong>{user.role==="admin"?"管理员":"普通用户"}</strong></div>
        <div><span><Activity size={16}/> 加入时间</span><strong>{date}</strong></div>
      </div>
      <p className="pb-identity-profile-note"><LockKeyhole size={15}/> 账号信息由服务器安全保存。资料修改功能将在后续版本开放。</p>
      <button className="pb-identity-secondary-full" type="button" onClick={close}>返回工作台 <ArrowUpRight size={16}/></button>
    </section>
  </div>;
}

function AdminPanel({ close, currentId }: { close: () => void; currentId: number }) {
  useDialogEscape(close);
  const [users, setUsers] = useState<AccountUser[]>([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<UserFilter>("all");
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<AccountUser | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    try {
      const data = await request<AccountUser[]>("users");
      setUsers(data);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取账号信息");
    } finally {
      setFetching(false);
    }
  }, []);
  useEffect(()=>{void load();},[load]);
  const counts = useMemo(()=>({
    total: users.length,
    active: users.filter(item=>item.active).length,
    disabled: users.filter(item=>!item.active).length,
  }),[users]);
  const filtered = useMemo(()=>users.filter(item=>{
    const matchesText = (item.username+" "+item.email).toLowerCase().includes(search.trim().toLowerCase());
    return matchesText && (filter==="all" || (filter==="active" && item.active) || (filter==="disabled" && !item.active));
  }),[users,search,filter]);
  const update = async (target: AccountUser) => {
    setConfirm(null);
    setSaving(target.id);
    try {
      await request("users/"+target.id+"/enabled","POST",{enabled:!target.active});
      await load();
    } catch(cause) {
      setError(cause instanceof Error ? cause.message : "操作未完成");
    } finally {
      setSaving(null);
    }
  };
  return <div className="pb-identity-overlay pb-identity-admin-overlay" onMouseDown={e=>{if(e.target===e.currentTarget&&!confirm)close();}}>
    <section className="pb-identity-modal pb-identity-admin" role="dialog" aria-modal="true" aria-labelledby="pb-admin-title">
      <header className="pb-identity-modal-header">
        <div><span className="pb-identity-kicker">POWERBID / ADMINISTRATION</span><h2 id="pb-admin-title">用户与权限</h2>
          <p>查看和管理工作空间的账号访问权限。</p></div>
        <CloseButton close={close}/>
      </header>
      <div className="pb-identity-stats">
        <div><span><Users size={16}/> 全部账号</span><strong>{counts.total}</strong><small>ACCOUNTS</small></div>
        <div><span><ShieldCheck size={16}/> 正常使用</span><strong>{counts.active}</strong><small>ACTIVE</small></div>
        <div><span><UserX size={16}/> 已禁用</span><strong>{counts.disabled}</strong><small>DISABLED</small></div>
      </div>
      <div className="pb-identity-admin-tools">
        <div className="pb-identity-admin-search"><Search size={17}/><input ref={searchRef} value={search} onChange={e=>setSearch(e.target.value)}
          placeholder="搜索用户名或邮箱…" aria-label="搜索账号"/>
          {search&&<button type="button" onClick={()=>{setSearch("");searchRef.current?.focus();}} aria-label="清除搜索"><X size={15}/></button>}</div>
        <div className="pb-identity-admin-filters" aria-label="按状态筛选">
          {([["all","全部"],["active","正常"],["disabled","已禁用"]] as const).map(([key,label])=>
            <button type="button" key={key} className={filter===key?"selected":""} onClick={()=>setFilter(key)} aria-pressed={filter===key}>{label}</button>)}
        </div>
      </div>
      {error&&<div className="pb-identity-error" role="alert">{error}<button onClick={()=>void load()} type="button">重试</button></div>}
      <div className="pb-identity-userlist">
        <div className="pb-identity-userlist-head"><span>用户</span><span>角色</span><span>状态</span><span>操作</span></div>
        {fetching ? <div className="pb-identity-empty"><span className="pb-identity-spinner"/> 正在加载账号…</div> :
        filtered.length === 0 ? <div className="pb-identity-empty"><Search size={23}/><strong>没有找到匹配账号</strong><span>尝试更换关键词或筛选条件。</span></div> :
        filtered.map(item=><div className="pb-identity-userrow" key={item.id}>
          <div className="pb-identity-usercell"><Monogram name={item.username}/><div><strong>{item.username}</strong><small title={item.email}>{item.email}</small></div></div>
          <span className="pb-identity-role">{item.role==="admin"?<ShieldCheck size={15}/>:<UserRound size={15}/>}
            {item.role==="admin"?"管理员":"成员"}</span>
          <span className={"pb-identity-status "+(item.active?"is-active":"is-disabled")}><span/>{item.active?"正常":"已禁用"}</span>
          <button className="pb-identity-table-action" type="button" disabled={saving!==null||item.id===currentId||item.role==="admin"}
            title={item.role==="admin"?"管理员账号不可在此修改":item.active?"禁用账号":"恢复账号"}
            onClick={()=>setConfirm(item)}>{saving===item.id?"处理中…":item.role==="admin"?"受保护":item.active?"禁用":"启用"}</button>
        </div>)}
      </div>
      <footer className="pb-identity-admin-footer"><span><ShieldCheck size={15}/> 禁用后将立即撤销该用户所有登录会话。</span>
        <span>展示最近的 {users.length} 个账号</span></footer>
    </section>
    {confirm&&<div className="pb-identity-confirm-wrap">
      <section role="alertdialog" aria-modal="true" aria-labelledby="pb-confirm-title" className="pb-identity-confirm">
        <div className={"pb-identity-confirm-symbol "+(confirm.active?"danger":"success")}>{confirm.active?<UserX size={23}/>:<ShieldCheck size={23}/>}</div>
        <h3 id="pb-confirm-title">{confirm.active?"确认禁用账号？":"恢复账号访问？"}</h3>
        <p>{confirm.active?"禁用后，该用户将立即退出所有设备并无法继续登录。":"恢复后，该用户可以重新登录 PowerBid 工作台。"}</p>
        <div className="pb-identity-confirm-user"><Monogram name={confirm.username}/><span>{confirm.username}<small>{confirm.email}</small></span></div>
        <div className="pb-identity-confirm-actions">
          <button type="button" onClick={()=>setConfirm(null)}>取消</button>
          <button className={confirm.active?"danger":""} type="button" onClick={()=>void update(confirm)}>
            {confirm.active?"确认禁用":"确认启用"} <Check size={16}/></button>
        </div>
      </section>
    </div>}
  </div>;
}

export default function AccountGate() {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [user, setUser] = useState<AccountUser | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [profileOpen, setProfileOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  useEffect(()=>{
    let alive = true;
    (async()=>{
      try {
        const settings = await request<AuthConfig>("config");
        if (!alive) return;
        setConfig(settings);
        if (settings.enabled) {
          try {
            const account = await request<AccountUser>("me");
            if (alive) setUser(account);
          } catch { /* no active session */ }
        }
      } catch(cause) {
        if (alive) setError(cause instanceof Error ? cause.message : "暂时无法连接账号服务");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return ()=>{alive=false;};
  },[]);
  const logout = async () => {
    try {
      await request("logout","POST");
      setUser(null);
      setProfileOpen(false);
      setAdminOpen(false);
    } catch(cause) {
      setError(cause instanceof Error ? cause.message : "退出失败");
    }
  };
  if (window.location.pathname.endsWith("/setup-admin")) return <AdminActivation/>;
  if (loading) return <div className="pb-identity-loading"><Fingerprint size={36}/><span>正在验证账号状态</span><span className="pb-identity-spinner"/></div>;
  if (!config) return <div className="pb-identity-loading"><Shield size={33}/><span>{error||"账号服务暂时不可用"}</span><button type="button" onClick={()=>window.location.reload()}>重新连接 <ArrowRight size={15}/></button></div>;
  const authPath = window.location.pathname.endsWith("/login") || window.location.pathname.endsWith("/register");
  if (!user && (config.enabled || authPath)) return <AuthScene config={config} onReady={setUser}/>;
  return <>
    <Workspace account={user} onLogout={config.enabled?logout:undefined}
      onOpenProfile={user?()=>setProfileOpen(true):undefined}
      onOpenAdmin={user?.role==="admin"?()=>setAdminOpen(true):undefined}/>
    {user && profileOpen && <ProfilePanel user={user} close={()=>setProfileOpen(false)}/>}
    {config.enabled && adminOpen && user && <AdminPanel currentId={user.id} close={()=>setAdminOpen(false)}/>}
  </>;
}
