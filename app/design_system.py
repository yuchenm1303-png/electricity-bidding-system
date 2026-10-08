"""PowerBid Studio · shared visual language for browser and desktop shells.

The theme is intentionally pure CSS + Streamlit. No remote font, image, or CDN
dependencies are required, so the same UI can run inside an offline webview.
"""

APP_CSS = r"""
<style>
:root {
  --pb-mint: #58dfc7;
  --pb-mint-soft: rgba(88,223,199,.12);
  --pb-blue: #8aabfa;
  --pb-cyan: #58dfc7;
  --pb-violet: #b09afc;
  --pb-amber: #ffcc89;
  --pb-red: #fd8c98;
  --pb-line: color-mix(in srgb,var(--text-color) 9%,transparent);
  --pb-line-strong: color-mix(in srgb,var(--text-color) 16%,transparent);
  --pb-muted: color-mix(in srgb,var(--text-color) 54%,transparent);
  --pb-radius-xl: 23px;
  --pb-radius-lg: 17px;
  --pb-radius-md: 12px;
}
html, body, [data-testid="stApp"], [data-testid="stSidebar"] {
  font-family: Inter,"SF Pro Display","SF Pro Text",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  font-feature-settings: "cv11" 1,"ss01" 1;
  -webkit-font-smoothing: antialiased;
}
html { scroll-behavior:smooth; }
body { letter-spacing:-.012em; }
.stApp {
  background:
    radial-gradient(ellipse 44rem 29rem at 65% -15%,rgba(83,141,232,.075),transparent 78%),
    radial-gradient(ellipse 35rem 34rem at 100% 42%,rgba(48,190,164,.027),transparent 78%),
    var(--background-color);
}
.stApp::before {
  content:""; position:fixed; z-index:0; inset:0; pointer-events:none; opacity:.14;
  background-image: radial-gradient(color-mix(in srgb,var(--text-color) 15%,transparent) .65px,transparent .65px);
  background-size:19px 19px; mask-image:linear-gradient(180deg,#000 0,transparent 74%);
}
[data-testid="stHeader"] { background:transparent; height:2rem; }
[data-testid="stDecoration"] { display:none; }
#MainMenu,footer { visibility:hidden; }
[data-testid="stAppViewBlockContainer"] {
  max-width:1510px; padding:1.05rem clamp(1.15rem,2.8vw,3rem) 5rem;
}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] { gap:.8rem; }
h1,h2,h3,p { letter-spacing:inherit; }
a { color:var(--pb-mint); }
::selection { background:rgba(88,223,199,.26); }

/* Sidebar / controls */
section[data-testid="stSidebar"] {
  width:304px !important; min-width:304px !important;
  background: color-mix(in srgb,var(--secondary-background-color) 79%,var(--background-color)) !important;
  border-right:1px solid var(--pb-line);
  box-shadow:15px 0 60px rgba(0,0,0,.07);
}
section[data-testid="stSidebar"] > div { padding-top:.55rem; }
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding:.35rem .78rem 1.15rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap:.64rem; }
[data-testid="stSidebar"] .stMarkdown p { margin:0; }
.pb-side-brand {
  display:flex; align-items:center; gap:.78rem; padding:.44rem .16rem 1.2rem;
  margin-bottom:.3rem; border-bottom:1px solid var(--pb-line);
}
.pb-side-logo {
  width:40px; height:40px; flex:0 0 40px; border-radius:13px; position:relative; overflow:hidden;
  display:grid;place-items:center;
  color:#081510; background:linear-gradient(145deg,#c5fff2,#64e8ce 54%,#5f9ec8);
  box-shadow:0 8px 22px rgba(50,216,184,.17),inset 0 1px rgba(255,255,255,.6);
}
.pb-side-logo::after { content:""; position:absolute; inset:1px; border-radius:12px; border:1px solid rgba(255,255,255,.32); pointer-events:none; }
.pb-side-title { font-size:.92rem; font-weight:760; letter-spacing:-.045em; line-height:1.25; color:var(--text-color); }
.pb-side-subtitle { font-size:.56rem; letter-spacing:.15em; font-weight:700; color:var(--pb-muted); margin-top:.19rem; }
.pb-live-dot {
  display:inline-block; flex:0 0 auto; width:7px;height:7px;border-radius:50%;
  background:var(--pb-mint); box-shadow:0 0 0 4px rgba(88,223,199,.10);
}
.pb-side-group-head { display:flex;align-items:center;justify-content:space-between;gap:.5rem;margin-bottom:.22rem; }
.pb-side-group-title { display:flex;align-items:center;gap:.58rem;color:var(--text-color);font-size:.80rem;font-weight:710; }
.pb-side-index {
  width:24px;height:24px;display:grid;place-items:center;border-radius:8px;
  font-family:ui-monospace,monospace;font-size:.66rem;font-weight:680;
  background:rgba(88,223,199,.10);color:var(--pb-mint);
  border:1px solid rgba(88,223,199,.12);
}
.pb-side-group-meta { font-size:.55rem;font-weight:710;letter-spacing:.15em;color:var(--pb-muted); }
.st-key-sidebar_market [data-testid="stVerticalBlockBorderWrapper"],
.st-key-sidebar_bid [data-testid="stVerticalBlockBorderWrapper"],
.st-key-sidebar_risk [data-testid="stVerticalBlockBorderWrapper"] {
  border:1px solid var(--pb-line) !important;
  border-radius:15px !important;
  background:color-mix(in srgb,var(--secondary-background-color) 50%,var(--background-color)) !important;
  box-shadow:inset 0 1px rgba(255,255,255,.024) !important;
}
.st-key-sidebar_market [data-testid="stVerticalBlockBorderWrapper"] > div,
.st-key-sidebar_bid [data-testid="stVerticalBlockBorderWrapper"] > div,
.st-key-sidebar_risk [data-testid="stVerticalBlockBorderWrapper"] > div { padding:.78rem .70rem .85rem !important; }
.st-key-sidebar_market [data-testid="stVerticalBlock"],
.st-key-sidebar_bid [data-testid="stVerticalBlock"],
.st-key-sidebar_risk [data-testid="stVerticalBlock"] { gap:.60rem !important; }
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p { font-size:.72rem!important;font-weight:620!important;color:var(--pb-muted)!important; }
[data-testid="stSidebar"] [data-testid="stNumberInput"] input,
[data-testid="stSidebar"] [data-testid="stSelectbox"] span { font-size:.81rem!important; }
[data-testid="stSidebar"] [data-testid="stNumberInput"] button {
  width:1.68rem!important;height:1.68rem!important;min-height:1.68rem!important;
  margin:.18rem .1rem!important;padding:0!important;border:0!important;border-radius:7px!important;
  background:transparent!important;opacity:.6;
}
[data-testid="stSidebar"] [data-testid="stNumberInput"] button:hover { opacity:1;background:var(--pb-mint-soft)!important; }
.pb-side-summary {
  display:grid;gap:.75rem;padding:1rem .91rem;border:1px solid rgba(88,223,199,.18);
  border-radius:15px;
  background:linear-gradient(145deg,rgba(88,223,199,.075),rgba(83,141,232,.018) 65%),var(--secondary-background-color);
}
.pb-side-summary-head { display:flex;justify-content:space-between;align-items:center;font-size:.76rem;font-weight:720; }
.pb-side-ready { display:inline-flex;align-items:center;gap:.35rem;color:var(--pb-mint);font-size:.60rem;letter-spacing:.13em; }
.pb-side-summary-grid { display:grid;grid-template-columns:1fr 1fr;gap:.79rem .55rem; }
.pb-side-summary-item span { display:block;font-size:.65rem;color:var(--pb-muted);margin-bottom:.18rem; }
.pb-side-summary-item strong { display:block;font-size:.77rem;overflow:hidden;white-space:nowrap;text-overflow:ellipsis; }
.pb-side-footnote { margin:.9rem 0 0;text-align:center;font-size:.62rem;color:var(--pb-muted);line-height:1.6; }

/* Inputs & accessibility */
[data-baseweb="input"] > div,
[data-baseweb="select"] > div,
[data-testid="stNumberInput"] > div > div,
[data-testid="stTextInput"] > div > div {
  min-height:2.63rem;
  border:1px solid var(--pb-line-strong)!important; border-radius:10px!important;
  background:color-mix(in srgb,var(--background-color) 65%,var(--secondary-background-color))!important;
  transition:border-color .17s ease,box-shadow .17s ease,background .17s ease;
}
[data-baseweb="input"] > div:hover,[data-baseweb="select"] > div:hover { border-color:rgba(88,223,199,.4)!important; }
[data-baseweb="input"] > div:focus-within,
[data-baseweb="select"] > div:focus-within,
[data-testid="stNumberInput"] > div > div:focus-within {
  border-color:rgba(88,223,199,.73)!important;
  box-shadow:0 0 0 3px rgba(88,223,199,.09)!important;
}
[data-testid="stNumberInput"] button { border-radius:8px!important;border:0!important;background:transparent!important; }
[data-baseweb="popover"] [role="listbox"] { border:1px solid var(--pb-line-strong);border-radius:12px;padding:.35rem;background:var(--secondary-background-color); }
[data-baseweb="popover"] [role="option"] { border-radius:8px; }
[data-testid="stSlider"] [data-baseweb="slider"] > div > div { height:4px; }
[data-testid="stSlider"] [role="slider"] { box-shadow:0 0 0 3px rgba(88,223,199,.1); }
button:focus-visible,[role="tab"]:focus-visible { outline:2px solid var(--pb-mint)!important;outline-offset:3px; }

/* Workspace / editorial hero */
.pb-topbar { display:flex;align-items:center;justify-content:space-between;gap:1rem;min-height:44px;margin:.15rem 0 1rem; }
.pb-breadcrumb { display:flex;align-items:center;gap:.6rem;font-size:.72rem;font-weight:650;color:var(--pb-muted); }
.pb-breadcrumb strong { color:var(--text-color);font-weight:700; }
.pb-breadcrumb .pb-crumb-separator { color:color-mix(in srgb,var(--text-color) 25%,transparent); }
.pb-top-status {
  display:inline-flex;align-items:center;gap:.55rem;flex-shrink:0;
  padding:.44rem .75rem;border-radius:999px;border:1px solid var(--pb-line);
  font-size:.66rem;letter-spacing:.02em;font-weight:680;color:var(--pb-muted);
  background:color-mix(in srgb,var(--secondary-background-color) 68%,transparent);
}
.pb-hero {
  position:relative;isolation:isolate;overflow:hidden;
  border-radius:25px;border:1px solid rgba(121,159,191,.17);
  background:
    radial-gradient(ellipse at 81% 28%,rgba(88,223,199,.10),transparent 40%),
    linear-gradient(120deg,rgba(91,130,172,.095),transparent 52%),
    color-mix(in srgb,var(--secondary-background-color) 78%,var(--background-color));
  padding:clamp(1.4rem,3vw,2.55rem);margin-bottom:1.15rem;
  box-shadow:0 24px 80px rgba(0,0,0,.07),inset 0 1px rgba(255,255,255,.04);
}
.pb-hero::before {
  content:"";position:absolute;pointer-events:none;inset:0 0 0 54%;opacity:.5;
  background-image:linear-gradient(rgba(88,223,199,.065) 1px,transparent 1px),linear-gradient(90deg,rgba(88,223,199,.065) 1px,transparent 1px);
  background-size:29px 29px;mask-image:linear-gradient(90deg,transparent,#000 45%);
}
.pb-hero-grid { position:relative;z-index:1;display:grid;grid-template-columns:minmax(0,1fr) minmax(245px,320px);align-items:center;gap:clamp(1.2rem,3vw,3rem); }
.pb-eyebrow { display:inline-flex;align-items:center;gap:.55rem;font-size:.67rem;font-weight:760;letter-spacing:.16em;text-transform:uppercase;color:var(--pb-mint); }
.pb-eyebrow-dot { width:5px;height:5px;border-radius:50%;background:var(--pb-mint);box-shadow:0 0 0 4px rgba(88,223,199,.11); }
.pb-hero h1 { color:var(--text-color);font-size:clamp(2.15rem,3.65vw,3.55rem);line-height:1.17;letter-spacing:-.056em;margin:.85rem 0 .8rem;font-weight:760; }
.pb-hero h1 em { font-style:normal;background:linear-gradient(110deg,#d3fff5 0%,#86e9d2 65%,#8ebcf5);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent; }
.pb-hero-copy { max-width:660px;color:color-mix(in srgb,var(--text-color) 62%,transparent);font-size:.84rem;line-height:1.9;margin:0; }
.pb-chip-row { display:flex;flex-wrap:wrap;gap:.49rem;margin-top:1.43rem; }
.pb-chip { display:inline-flex;align-items:center;gap:.43rem;padding:.39rem .72rem;border-radius:999px;font-size:.66rem;font-weight:640;color:color-mix(in srgb,var(--text-color) 70%,transparent);border:1px solid var(--pb-line);background:color-mix(in srgb,var(--background-color) 62%,transparent); }
.pb-chip-dot { width:6px;height:6px;border-radius:50%;background:var(--pb-mint); }
.pb-hero-panel {
  display:flex;flex-direction:column;justify-content:space-between;
  border-radius:19px;padding:1.08rem 1.15rem;min-height:205px;
  background:linear-gradient(160deg,rgba(88,223,199,.055),transparent 47%),color-mix(in srgb,var(--background-color) 73%,var(--secondary-background-color));
  border:1px solid rgba(88,223,199,.13);backdrop-filter:blur(10px);
}
.pb-hero-panel-head { display:flex;align-items:center;justify-content:space-between;gap:.5rem;font-size:.61rem;font-weight:760;letter-spacing:.13em;text-transform:uppercase;color:var(--pb-muted); }
.pb-hero-panel-head span:last-child { color:var(--pb-mint); }
.pb-hero-visual { display:flex;gap:.85rem;align-items:center;padding:1.1rem .1rem .72rem; }
.pb-orbit { position:relative;display:grid;place-items:center;width:92px;height:92px;flex:0 0 92px; }
.pb-orbit::before,.pb-orbit::after { content:"";position:absolute;inset:0;border-radius:50%;border:1px solid rgba(88,223,199,.21); }
.pb-orbit::after { inset:12px;border:1px dashed rgba(88,223,199,.32);animation:pbOrbit 30s linear infinite; }
.pb-orbit-core { display:grid;place-items:center;width:43px;height:43px;border-radius:15px;color:var(--pb-mint);font-size:1.35rem;background:var(--pb-mint-soft);box-shadow:0 0 24px rgba(88,223,199,.1); }
.pb-orbit-dot { position:absolute;top:3px;left:50%;width:7px;height:7px;border-radius:50%;background:var(--pb-mint);box-shadow:0 0 13px rgba(88,223,199,.9); }
.pb-hero-panel-value { color:var(--text-color);font-size:1.2rem;font-weight:770;letter-spacing:-.036em; }
.pb-hero-panel-sub { color:var(--pb-muted);font-size:.69rem;line-height:1.65;margin-top:.34rem; }
.pb-panel-divider { height:1px;background:var(--pb-line);margin:.2rem 0 .65rem; }
.pb-panel-foot { display:flex;align-items:center;justify-content:space-between;gap:1rem;font-size:.63rem;color:var(--pb-muted); }
.pb-panel-foot strong { color:var(--pb-mint);font-size:.65rem;font-weight:690; }

/* Chapter headings / cards */
.pb-section-head { display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin:1.82rem 0 .68rem; }
.pb-section-kicker { display:flex;align-items:center;gap:.53rem;font-size:.64rem;color:var(--pb-mint);letter-spacing:.14em;text-transform:uppercase;font-weight:760; }
.pb-section-kicker::before { content:"";display:block;width:18px;height:1px;background:var(--pb-mint);opacity:.7; }
.pb-section-title { color:var(--text-color);font-size:1.24rem;font-weight:755;letter-spacing:-.038em;margin-top:.35rem; }
.pb-section-desc { color:var(--pb-muted);font-size:.75rem;line-height:1.7;max-width:780px;margin-top:.26rem; }
[data-testid="stMetric"] {
  min-height:122px;position:relative;overflow:hidden;
  padding:1.05rem 1.1rem 1.1rem;
  border:1px solid var(--pb-line);border-radius:16px;
  background:color-mix(in srgb,var(--secondary-background-color) 62%,var(--background-color));
  transition:border-color .2s ease,transform .2s ease,box-shadow .2s ease;
}
[data-testid="stMetric"]::after { content:"";position:absolute;bottom:0;left:0;right:0;height:2px;opacity:.5;background:linear-gradient(90deg,var(--pb-mint),transparent 60%); }
[data-testid="stMetric"]:hover { border-color:rgba(88,223,199,.28);transform:translateY(-2px);box-shadow:0 14px 35px rgba(0,0,0,.08); }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) [data-testid="stMetric"]::after { background:linear-gradient(90deg,var(--pb-blue),transparent 60%); }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) [data-testid="stMetric"]::after { background:linear-gradient(90deg,var(--pb-violet),transparent 60%); }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4) [data-testid="stMetric"]::after { background:linear-gradient(90deg,var(--pb-amber),transparent 60%); }
[data-testid="stMetricLabel"] { color:var(--pb-muted);font-size:.73rem;font-weight:670; }
[data-testid="stMetricValue"] { margin-top:.38rem;color:var(--text-color);font-size:1.64rem;font-weight:730;letter-spacing:-.042em; }
[data-testid="stVerticalBlockBorderWrapper"] {
  border:1px solid var(--pb-line)!important;border-radius:17px!important;
  background:color-mix(in srgb,var(--secondary-background-color) 58%,var(--background-color));
  box-shadow:inset 0 1px rgba(255,255,255,.015);
}
[data-testid="stVerticalBlockBorderWrapper"] > div { padding:.23rem; }
.st-key-offer_card [data-testid="stVerticalBlockBorderWrapper"] { background:color-mix(in srgb,var(--secondary-background-color) 67%,var(--background-color)); }
.st-key-run_card [data-testid="stVerticalBlockBorderWrapper"] { border-color:rgba(88,223,199,.22)!important;background:linear-gradient(110deg,rgba(88,223,199,.05),transparent 55%),color-mix(in srgb,var(--secondary-background-color) 58%,var(--background-color)); }
.pb-card-heading { display:flex;align-items:center;justify-content:space-between;gap:1rem; }
.pb-card-title { font-size:.9rem;font-weight:720;color:var(--text-color); }
.pb-card-meta { display:inline-flex;padding:.32rem .58rem;border:1px solid var(--pb-line);border-radius:999px;font-size:.63rem;white-space:nowrap;color:var(--pb-muted); }
.pb-note { display:flex;align-items:flex-start;gap:.8rem;padding:.9rem 1rem;margin:.8rem 0 1rem;border-radius:14px;border:1px solid rgba(88,223,199,.15);background:rgba(88,223,199,.04); }
.pb-note-mark { display:grid;place-items:center;width:24px;height:24px;flex:0 0 24px;border-radius:8px;background:var(--pb-mint-soft);font-size:.72rem;font-weight:800;color:var(--pb-mint); }
.pb-note-copy { color:var(--pb-muted);font-size:.75rem;line-height:1.7; }
.pb-note-copy strong { color:var(--text-color); }
.pb-action-copy { padding:.2rem 0; }
.pb-action-title { font-size:.94rem;font-weight:725;color:var(--text-color); }
.pb-action-desc { font-size:.72rem;color:var(--pb-muted);margin-top:.35rem;line-height:1.6; }
.pb-result-banner { display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:1rem 1.1rem;margin:.45rem 0 1rem;border:1px solid rgba(88,223,199,.2);border-radius:14px;background:linear-gradient(110deg,rgba(88,223,199,.075),rgba(88,223,199,.018));color:var(--pb-muted);font-size:.74rem; }
.pb-result-banner strong { color:var(--pb-mint); }

/* Buttons, data, charts */
.stButton > button,.stDownloadButton > button {
  min-height:2.8rem;border-radius:10px!important;font-weight:710;letter-spacing:-.015em;
  border:1px solid var(--pb-line-strong);
  transition:transform .2s ease,background .2s ease,box-shadow .2s ease,border-color .2s ease;
}
.stButton > button[kind="primary"] {
  color:#06241e!important;background:linear-gradient(110deg,#a0f3e1,#5bddc7)!important;
  border:1px solid rgba(125,249,221,.6)!important;
  box-shadow:0 12px 28px rgba(52,217,184,.15),inset 0 1px rgba(255,255,255,.38);
}
.stButton > button[kind="primary"] p { color:#06241e!important; }
.stButton > button:hover,.stDownloadButton > button:hover { border-color:rgba(88,223,199,.45);transform:translateY(-1px); }
.stButton > button[kind="primary"]:hover { box-shadow:0 15px 32px rgba(52,217,184,.24),inset 0 1px rgba(255,255,255,.44); }
.stButton > button:active,.stDownloadButton > button:active { transform:translateY(0); }
[data-testid="stDataFrame"],[data-testid="stDataEditor"] {
  border:1px solid var(--pb-line);border-radius:12px;overflow:hidden;
  background:color-mix(in srgb,var(--background-color) 75%,var(--secondary-background-color));
}
[data-testid="stDataFrame"] [role="grid"],[data-testid="stDataEditor"] [role="grid"] { border:0!important; }
[data-testid="stTabs"] [data-baseweb="tab-list"] { display:flex;gap:.25rem;padding:.28rem;border:1px solid var(--pb-line);border-radius:12px;background:color-mix(in srgb,var(--secondary-background-color) 55%,var(--background-color)); }
[data-testid="stTabs"] [data-baseweb="tab"] { border-radius:9px;height:2.45rem;padding:0 .95rem;color:var(--pb-muted);font-size:.74rem;font-weight:685; }
[data-testid="stTabs"] [data-baseweb="tab-highlight"] { display:none; }
[data-testid="stTabs"] [aria-selected="true"] { background:color-mix(in srgb,var(--background-color) 75%,var(--secondary-background-color));color:var(--text-color)!important;box-shadow:0 3px 12px rgba(0,0,0,.04); }
[data-testid="stExpander"] { border-radius:12px;overflow:hidden;border-color:var(--pb-line); }
[data-testid="stAltairChart"] { border-radius:12px;overflow:hidden; }
[data-testid="stAlert"] { border-radius:12px; }
hr { border-color:var(--pb-line)!important; }
* { scrollbar-width:thin;scrollbar-color:color-mix(in srgb,var(--text-color) 22%,transparent) transparent; }
*::-webkit-scrollbar { width:8px;height:8px; }
*::-webkit-scrollbar-thumb { border:2px solid transparent;border-radius:99px;background:color-mix(in srgb,var(--text-color) 23%,transparent);background-clip:padding-box; }

@keyframes pbRise { from { opacity:0;transform:translateY(9px); } to { opacity:1;transform:translateY(0); } }
@keyframes pbOrbit { to { transform:rotate(360deg); } }
.pb-hero,.pb-section-head { animation:pbRise .38s cubic-bezier(.2,.7,.3,1) both; }
@media (max-width:1110px) {
  .pb-hero-grid { grid-template-columns:1fr; }
  .pb-hero-panel { display:none; }
}
@media (max-width:900px) {
  [data-testid="stAppViewBlockContainer"] { padding:.8rem .9rem 3rem; }
  section[data-testid="stSidebar"] { width:294px!important;min-width:294px!important; }
  .pb-hero { border-radius:19px;padding:1.5rem 1.2rem; }
  .pb-hero h1 { font-size:clamp(1.95rem,7vw,2.65rem); }
  .pb-section-head,.pb-result-banner { align-items:flex-start;flex-direction:column; }
  .pb-top-status { font-size:.59rem; }
}
@media (max-width:510px) {
  .pb-topbar { gap:.4rem; }
  .pb-breadcrumb { gap:.3rem;font-size:.64rem; }
  .pb-top-status { padding:.33rem .49rem; }
  .pb-hero h1 { letter-spacing:-.04em; }
}
@media (prefers-reduced-motion:reduce) {
  *,*::before,*::after { animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important;scroll-behavior:auto!important; }
}
</style>
"""