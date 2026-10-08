import { useEffect, useState } from "react";
import { ChevronDown, ChevronLeft, SlidersHorizontal, Activity, Gauge, CircleHelp } from "lucide-react";
import type { Settings, Mode } from "./types";

type Props = {
  config: Settings;
  onChange: (next: Settings) => void;
  onClose: () => void;
  collapsed: boolean;
  onModeChange: (mode: Mode) => void;
};

function NumberField({ label, value, onCommit, min = 0, step = 1, suffix, description }: {
  label: string;
  value: number;
  onCommit: (value: number) => void;
  min?: number;
  step?: number;
  suffix?: string;
  description?: string;
}) {
  const [raw, setRaw] = useState(String(value));
  useEffect(() => { setRaw(String(value)); }, [value]);
  const commit = () => {
    const val = Number(raw);
    if (raw.trim() !== "" && Number.isFinite(val) && val >= min) onCommit(val);
    else setRaw(String(value));
  };
  return (
    <label className="field">
      <span className="field-label">{label}{description && <span title={description} className="hint"><CircleHelp size={13}/></span>}</span>
      <span className="number-field">
        <input type="number" value={raw} step={step} min={min} onChange={e => setRaw(e.target.value)}
          onBlur={commit} onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") { setRaw(String(value)); e.currentTarget.blur(); } }} />
        {suffix && <span className="number-unit">{suffix}</span>}
      </span>
    </label>
  );
}

function RangeField({ label, value, onChange, max = 40, unit = "%" }: {
  label: string; value: number; onChange: (value: number) => void; max?: number; unit?: string;
}) {
  const display = Math.round(value * 100);
  return (
    <label className="range-field">
      <span className="range-head"><span>{label}</span><strong>{display}{unit}</strong></span>
      <input type="range" min={0} max={max} step={5} value={display} onChange={e => onChange(Number(e.target.value) / 100)} />
    </label>
  );
}

export function SettingsPanel({ config, onChange, onClose, collapsed, onModeChange }: Props) {
  const set = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    onChange({ ...config, [key]: value });
  if (collapsed) return (
    <div className="settings-closed">
      <button type="button" className="icon-button" onClick={onClose} title="展开参数面板" aria-label="展开参数面板">
        <SlidersHorizontal size={18} />
      </button>
    </div>
  );
  return (
    <aside className="settings-panel" aria-label="报价策略参数">
      <div className="settings-top">
        <div className="settings-heading"><div className="settings-emblem"><SlidersHorizontal size={17} /></div>
          <div><h3>策略参数</h3><p>SCENARIO CONTROLS</p></div></div>
        <button className="icon-button" onClick={onClose} title="收起参数面板" aria-label="收起参数面板"><ChevronLeft size={18}/></button>
      </div>
      <div className="settings-scroll">
        <div className="setting-section">
          <div className="setting-section-head"><Activity size={15}/><span>市场环境</span><small>01</small></div>
          <NumberField label="市场负荷" value={config.demand_mw} step={10} suffix="MW" onCommit={v => set("demand_mw", v)}/>
          <NumberField label="结算时长" value={config.interval_hours} step={0.25} min={0.25} suffix="h" onCommit={v => set("interval_hours", v)}/>
          <label className="field"><span className="field-label">目标机组</span><span className="select-wrap">
            <select value={config.target_unit_id} onChange={e => set("target_unit_id", e.target.value)}>
              {config.offers.map(o => <option key={o.unit_id} value={o.unit_id}>{o.unit_id}</option>)}
            </select><ChevronDown size={15}/></span></label>
          <label className="field"><span className="field-label">出清引擎</span><span className="select-wrap">
            <select value={config.engine} onChange={e => set("engine", e.target.value as Settings["engine"])}>
              <option value="uniform">统一出清价</option><option value="pypsa">PyPSA（需安装）</option>
            </select><ChevronDown size={15}/></span></label>
        </div>
        <div className="setting-section">
          <div className="setting-section-head"><Gauge size={15}/><span>报价策略</span><small>02</small></div>
          <span className="field-label">决策模式</span>
          <div className="mode-switch" role="group" aria-label="决策模式">
            <button type="button" className={config.mode === "single" ? "active" : ""} onClick={() => onModeChange("single")}>单场景</button>
            <button type="button" className={config.mode === "risk" ? "active" : ""} onClick={() => onModeChange("risk")}>风险分析</button>
          </div>
          <div className="field-pair">
            <NumberField label="最低报价" value={config.start} step={10} onCommit={v => set("start", v)}/>
            <NumberField label="最高报价" value={config.stop} step={10} onCommit={v => set("stop", v)}/>
          </div>
          <NumberField label="搜索步长" value={config.step} min={0.1} step={1} onCommit={v => set("step", v)}/>
        </div>
        {config.mode === "risk" && <div className="setting-section risk-settings">
          <div className="setting-section-head"><Activity size={15}/><span>风险控制</span><small>03</small></div>
          <RangeField label="负荷波动范围" value={config.demand_uncertainty} onChange={v => set("demand_uncertainty", v)}/>
          <RangeField label="竞争报价波动" value={config.competitor_uncertainty} onChange={v => set("competitor_uncertainty", v)}/>
          <RangeField label="风险厌恶程度" value={config.risk_aversion} max={100} onChange={v => set("risk_aversion", v)}/>
          <RangeField label="下行情景比例" value={config.tail_fraction} max={100} onChange={v => set("tail_fraction", Math.max(0.05, v))}/>
          <p className="settings-disclaimer">当前为等权压力情景，并非市场价格预测。</p>
        </div>}
      </div>
      <div className="settings-foot"><span className="online-dot"/><span>所有参数只作用于本次模拟</span></div>
    </aside>
  );
}
