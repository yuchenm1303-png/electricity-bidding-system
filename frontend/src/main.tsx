import React, { Suspense } from "react";
import ReactDOM from "react-dom/client";
import LandingPage from "./LandingPage";

// Keep the full functional workbench (and its heavier chart dependencies)
// out of the public homepage's initial JavaScript chunk.
const Workspace = React.lazy(() => import("./AccountGate"));
const base = import.meta.env.BASE_URL;
const route = window.location.pathname.startsWith(base)
  ? window.location.pathname.slice(base.length)
  : window.location.pathname.replace(/^\/+/, "");
const inWorkspace = route === "login" || route === "register" || route === "app" || route.startsWith("app/")
  || new URLSearchParams(window.location.search).get("workspace") === "1";
const workspaceHref = base + "app";

// Default to dark on first visit, but respect the user's explicit choice.
// Set the root before React mounts to prevent a flash of light UI.
let storedTheme: string | null = null;
try { storedTheme = window.localStorage.getItem("powerbid-theme-preference-v2"); } catch { /* storage disabled */ }
document.documentElement.dataset.theme = storedTheme === "light" ? "light" : "dark";
document.documentElement.style.colorScheme = storedTheme === "light" ? "light" : "dark";
if (inWorkspace) document.title = "PowerBid Studio · 报价策略工作台";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {inWorkspace
      ? <Suspense fallback={<div style={{minHeight:"100vh",display:"grid",placeItems:"center",fontFamily:"sans-serif",color:"#5262dc"}}>正在进入 PowerBid 工作台…</div>}><Workspace/></Suspense>
      : <LandingPage workspaceHref={workspaceHref}/>}
  </React.StrictMode>
);
