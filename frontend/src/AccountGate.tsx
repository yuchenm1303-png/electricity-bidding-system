import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight, LockKeyhole, Mail, Shield, ShieldCheck, UserRound, Users, X } from "lucide-react";
import Workspace from "./WorkspaceEntry";
import "./account.css";

export type AccountUser={id:number;username:string;email:string;role:"admin"|"member";active:boolean;created_at?:number};
type AuthConfig={enabled:boolean;registration_open:boolean};
const base=import.meta.env.BASE_URL;

async function request<T>(path:string,method="GET",data?:unknown):Promise<T>{
  const res=await fetch(base+"api/auth/"+path,{method,credentials:"same-origin",
    headers:{"X-PowerBid-Request":"1",...(data===undefined?{}:{"Content-Type":"application/json"})},
    body:data===undefined?undefined:JSON.stringify(data)});
  const json=await res.json().catch(()=>({}));
  if(!res.ok)throw new Error(typeof json.detail==="string"?json.detail:"请求失败，请稍后再试");
  return json as T;
}
function AuthForm({config,onReady}:{config:AuthConfig;onReady:(user:AccountUser)=>void}){
  const [register,setRegister]=useState(false);
  const [name,setName]=useState("");
  const [email,setEmail]=useState("");
  const [password,setPassword]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const submit=async(e:FormEvent<HTMLFormElement>)=>{
    e.preventDefault();setBusy(true);setError("");
    try{
      const body=register?{username:name.trim(),email:email.trim(),password}:{username:name.trim(),password};
      const user=await request<AccountUser>(register?"register":"login","POST",body);
      setPassword("");
      window.history.replaceState(null,"",base+"app");
      onReady(user);
    }catch(e){setError(e instanceof Error?e.message:"操作失败");}
    finally{setBusy(false);}
  };
  return <div className="pb-auth-screen">
    <div className="pb-auth-background" aria-hidden="true"><span/><span/><span/></div>
    <main className="pb-auth-frame">
      <a href={base} className="pb-auth-back"><ArrowLeft size={16}/>返回 PowerBid 首页</a>
      <section className="pb-auth-panel">
        <div className="pb-auth-symbol"><ShieldCheck size={28} strokeWidth={1.6}/></div>
        <div className="pb-auth-kicker">POWERBID / SECURE ACCESS</div>
        <h1>{register?"创建研究账号":"欢迎回到 PowerBid"}</h1>
        <p>{register?"注册后进入电力市场报价研究工作台。":"登录后继续电力市场报价与风险分析。"}</p>
        <form onSubmit={submit} className="pb-auth-form">
          <label htmlFor="auth-name"><UserRound size={16}/>用户名</label>
          <input id="auth-name" autoComplete="username" minLength={3} maxLength={32} pattern="[A-Za-z][A-Za-z0-9_-]{2,31}"
             value={name} onChange={e=>setName(e.target.value)} required placeholder="输入用户名"/>
          {register&&<><label htmlFor="auth-email"><Mail size={16}/>邮箱</label>
             <input id="auth-email" type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)}
               required placeholder="name@example.com"/></>}
          <label htmlFor="auth-password"><LockKeyhole size={16}/>密码</label>
          <input id="auth-password" type="password" autoComplete={register?"new-password":"current-password"}
            minLength={12} maxLength={128} required value={password} onChange={e=>setPassword(e.target.value)}
            placeholder="至少 12 位字符"/>
          {error&&<div className="pb-auth-error" role="alert">{error}</div>}
          <button className="pb-auth-submit" disabled={busy} type="submit">{busy?"请稍候…":register?"创建账号":"登录工作台"}<ArrowRight size={17}/></button>
        </form>
        {config.registration_open
          ?<div className="pb-auth-switch">{register?"已有账号？":"还没有账号？"}
             <button type="button" onClick={()=>{setRegister(!register);setPassword("");setError("");}}>{register?"返回登录":"立即注册"}</button></div>
          :<div className="pb-auth-switch">当前为邀请使用阶段，如需账号请联系管理员。</div>}
      </section>
      <p className="pb-auth-footer">教学仿真环境 · 研究用途 · 不进行真实市场交易</p>
    </main>
  </div>;
}
function AdminPanel({close}:{close:()=>void}){
 const [users,setUsers]=useState<AccountUser[]>([]);
 const [error,setError]=useState("");
 const [saving,setSaving]=useState<number|null>(null);
 const load=useCallback(async()=>{try{setUsers(await request<AccountUser[]>("users"));setError("");}catch(e){setError(e instanceof Error?e.message:"无法读取用户");}},[]);
 useEffect(()=>{void load();},[load]);
 const update=async(user:AccountUser)=>{
   setSaving(user.id);
   try{await request("users/"+user.id+"/enabled","POST",{enabled:!user.active});await load();}
   catch(e){setError(e instanceof Error?e.message:"操作失败");}finally{setSaving(null);}
 };
 return <div className="pb-admin-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)close();}}>
   <section className="pb-admin-panel" role="dialog" aria-modal="true" aria-label="账号管理">
     <header><div><span><Users size={18}/>ACCOUNT MANAGEMENT</span><h2>账号与权限管理</h2></div>
       <button type="button" onClick={close} aria-label="关闭"><X size={20}/></button></header>
     <p>禁用账号将立即撤销其全部会话。管理员不能禁用自己。</p>
     {error&&<div className="pb-auth-error" role="alert">{error}</div>}
     <div className="pb-admin-list">
       {users.map(u=><div className="pb-admin-row" key={u.id}>
         <span className="pb-admin-avatar">{u.username.charAt(0).toUpperCase()}</span>
         <div><strong>{u.username}</strong><small>{u.email} · {u.role==="admin"?"管理员":"普通用户"}</small></div>
         <span className={u.active?"pb-admin-state active":"pb-admin-state"}>{u.active?"正常":"已禁用"}</span>
         <button type="button" disabled={saving!==null||u.role==="admin"} onClick={()=>update(u)}>
           {saving===u.id?"处理中":u.active?"禁用":"启用"}
         </button>
       </div>)}
     </div>
   </section>
 </div>;
}
export default function AccountGate(){
 const [config,setConfig]=useState<AuthConfig|null>(null);
 const [user,setUser]=useState<AccountUser|null>(null);
 const [error,setError]=useState("");
 const [loading,setLoading]=useState(true);
 const [adminOpen,setAdminOpen]=useState(false);
 useEffect(()=>{
   let live=true;
   (async()=>{
     try{
       const cfg=await request<AuthConfig>("config");
       if(!live)return;setConfig(cfg);
       if(cfg.enabled){try{const me=await request<AccountUser>("me");if(live)setUser(me);}catch{/* unauthenticated */}}
     }catch(e){if(live)setError(e instanceof Error?e.message:"无法连接账号服务");}
     finally{if(live)setLoading(false);}
   })();
   return ()=>{live=false};
 },[]);
 const logout=async()=>{try{await request("logout","POST");setUser(null);setAdminOpen(false);}catch(e){setError(e instanceof Error?e.message:"退出失败");}};
 if(loading)return <div className="pb-auth-loading"><Shield size={30}/>正在验证账号状态…</div>;
 if(!config)return <div className="pb-auth-loading"><Shield size={30}/>{error||"账号服务暂时不可用"}<button onClick={()=>location.reload()}>重试</button></div>;
 if(config.enabled&&!user)return <AuthForm config={config} onReady={setUser}/>;
 return <>
   <Workspace account={user} onLogout={config.enabled?logout:undefined}
     onOpenAdmin={user?.role==="admin"?()=>setAdminOpen(true):undefined}/>
   {config.enabled&&adminOpen&&<AdminPanel close={()=>setAdminOpen(false)}/>}
 </>;
}
