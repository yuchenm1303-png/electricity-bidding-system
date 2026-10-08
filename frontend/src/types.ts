export type Offer = {
  unit_id: string;
  quantity_mw: number;
  bid_price: number;
  marginal_cost: number;
};
export type Scenario = {
  name: string;
  description: string;
  data_source: string;
  demand_mw: number;
  interval_hours: number;
  target_unit_id: string;
  offers: Offer[];
};
export type Mode = "single" | "risk";
export type Engine = "uniform" | "pypsa";
export type WorkspaceView = "workspace" | "units" | "analysis" | "risk" | "trials";
export type Settings = {
  demand_mw: number;
  interval_hours: number;
  target_unit_id: string;
  offers: Offer[];
  start: number;
  stop: number;
  step: number;
  mode: Mode;
  engine: Engine;
  demand_uncertainty: number;
  competitor_uncertainty: number;
  risk_aversion: number;
  tail_fraction: number;
};
export type SingleTrial = {
  bid_price: number;
  clearing_price: number | null;
  accepted_mw: number;
  revenue: number;
  variable_cost: number;
  profit: number;
  feasible: boolean;
};
export type RiskOutcome = {
  name: string;
  probability: number;
  profit: number;
  accepted_mw: number;
  clearing_price: number | null;
  feasible: boolean;
};
export type RiskTrial = {
  bid_price: number;
  expected_profit: number;
  downside_profit: number;
  worst_profit: number;
  expected_accepted_mw: number;
  feasible_probability: number;
  score: number;
  outcomes: RiskOutcome[];
};
export type Report = {
  mode: Mode;
  target_unit_id: string;
  best: SingleTrial | RiskTrial;
  trials: SingleTrial[] | RiskTrial[];
  count: number;
  data_source: string;
};
export const asSingle = (trial: SingleTrial | RiskTrial): SingleTrial => trial as SingleTrial;
export const asRisk = (trial: SingleTrial | RiskTrial): RiskTrial => trial as RiskTrial;
export const numeric = (value: number, digits = 0) =>
  Number.isFinite(value)
    ? value.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : "—";
export const csvExport = (filename: string, columns: string[], rows: (string | number | boolean | null | undefined)[][]) => {
  const cell = (val: string | number | boolean | null | undefined) => {
    const text = val == null ? "" : String(val);
    return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  };
  const csv = [columns, ...rows].map(row => row.map(cell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};
