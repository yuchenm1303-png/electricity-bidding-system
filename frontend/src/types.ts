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
export type WorkspaceView = "workspace" | "units" | "analysis" | "risk" | "trials" | "pmss";
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

export type PMSSUnit = {
  unit_id: string;
  name: string;
  capacity_mw: number;
  min_power_mw: number;
  running_cost: number;
  unit_type: string;
};
export type PMSSNetworkHour = {
  hour: number;
  nodes_with_price: number;
  branches_with_flow: number;
  mean_lmp: number | null;
  lmp_spread: number | null;
  nonzero_shadow_branches: number;
  max_abs_shadow: number | null;
  max_abs_flow_mw: number | null;
};
export type PMSSInspection = {
  units: PMSSUnit[];
  load_mw: number[];
  forecast_source: string;
  case_date: string;
  historical_only: boolean;
  load_source_kind: string;
  max_segments: number;
  technical_evidence: {
    unit_count: number;
    capacity_match_count: number;
    minimum_match_count: number;
    source_claim_only: true;
    technical_inputs_verified: false;
    joint_milp_ready: false;
    observed_fields: Record<string, {
      present: number;
      zero: number;
      distinct: number;
      min: number | null;
      max: number | null;
      meaning: string;
      validated_for_joint_milp: false;
    }>;
    note: string;
  } | null;
  joint_readiness: {
    ready: boolean;
    total_units: number;
    supplied_units: number;
    missing_unit_ids: string[];
    unexpected_unit_ids: string[];
    invalid: Record<string, string>;
    source: string;
    independently_verified: boolean;
    message: string;
  };
  joint_required_technical_fields: string[];
  historical_bid_rule_audit: {
    price_floor: number | null;
    price_ceiling: number | null;
    original_units_outside_current_range: number;
    original_segments_outside_current_range: number;
    largest_original_price: number;
    affected_unit_names: string[];
    interpretation: string;
  };
  dc_grid_available: boolean;
  dc_grid_buses: number;
  dc_grid_lines: number;
  network: {
    node_count: number;
    branch_count: number;
    price_coverage_points: number;
    flow_coverage_points: number;
    hourly: PMSSNetworkHour[];
    most_shadowed: {
      element_id: string;
      name: string;
      hours_nonzero_shadow: number;
      peak_abs_shadow: number;
      peak_abs_flow_mw: number | null;
    }[];
  } | null;
};
export type PMSSOptimization = {
  target_unit_id: string;
  baseline: {total_profit: number; total_accepted_mwh: number};
  recommended: {
    segments: {start_power: number; end_power: number; price: number}[];
    total_profit: number;
    total_accepted_mwh: number;
    hours: {
      period: number;
      demand_mw: number;
      clearing_price: number | null;
      target_accepted_mw: number;
      target_profit: number;
    }[];
  };
  evaluated_curves: number;
  baseline_backtest: {
    power_mae_mw: number | null;
    power_rmse_mw: number | null;
    observed_power_points: number;
    hours: {
      hour: number;
      observed_accepted_mw: number | null;
      surrogate_accepted_mw: number;
    }[];
  } | null;
  model: string;
  pmss_write_performed: false;
  pmss_clearing_executed: false;
  counterfactual_pmss_result_available: false;
};

export type DCNetworkStudy = {
  target_unit_id: string;
  total_profit: number;
  total_accepted_mwh: number;
  max_line_utilization: number;
  hours_with_binding_lines: number;
  study_type: string;
  hours: {
    period: number;
    target_mw: number;
    target_lmp: number;
    target_profit: number;
    binding_line_count: number;
    binding_lines: string[];
  }[];
};
export type PMSSHistoricalGridAudit = {
  case_date: string;
  market_type: "DA";
  node_count: number;
  line_count: number;
  unit_count: number;
  balanced_hour_count: number;
  observed_missing_hours: number;
  total_day_ahead_energy_mwh: number;
  generation_load_mae_mw: number | null;
  bus_balance_mae_mw: number | null;
  reverse_flow_bus_balance_mae_mw: number | null;
  modeled_target_dispatch_mae_mw: number | null;
  modeled_nodal_price_mae: number | null;
  modeled_abs_flow_mae_mw: number | null;
  modeled_price_matching_hours: number;
  modeled_price_mismatch_periods: number[];
  modeled_price_mismatch_points: number;
  modeled_peak_node_price: number | null;
  observed_peak_node_price: number | null;
  observed_line_over_nameplate_hours: number;
  hours: {
    period: number;
    observed_generation_mw: number | null;
    day_ahead_load_mw: number;
    system_generation_minus_load_mw: number | null;
    observed_bus_balance_mae_mw: number | null;
    observed_bus_balance_reverse_mae_mw: number | null;
    max_observed_bus_balance_error_mw: number | null;
    observed_line_over_nameplate_count: number;
    complete_observation: boolean;
    modeled_target_dispatch_error_mw: number | null;
    modeled_nodal_price_mae: number | null;
    modeled_abs_flow_mae_mw: number | null;
  }[];
  worst_bus_balance: {element_id: string; mae: number; points: number}[];
  worst_nodal_model_prices: {element_id: string; mae: number; points: number}[];
  worst_line_model_flows: {element_id: string; mae: number; points: number}[];
  disclaimer: string;
};
export type PMSSNetworkComparison = {
  historical_grid_audit: PMSSHistoricalGridAudit | null;
  historical_unavailable_reason: string | null;
  baseline: DCNetworkStudy;
  recommended: DCNetworkStudy | null;
  recommended_error: string | null;
  topology_source: string;
  network_model: string;
  excluded_constraints: string[];
  pmss_write_performed: false;
  pmss_clearing_executed: false;
  pmss_counterfactual_verified: false;
};

export type PMSSRankedCurve = {
  name: string;
  score: number;
  expected_margin: number;
  downside_margin: number;
  worst_margin: number;
  expected_accepted_mwh: number;
  price_blocks: [number, number, number][];
};
export type PMSSNetworkRank = {
  target_unit_id: string;
  baseline_score: number;
  baseline_expected_margin: number;
  baseline_rule_compatible: boolean;
  eligible_candidates: PMSSRankedCurve[];
  best_candidate: PMSSRankedCurve;
  modeled_better_than_baseline: boolean | null;
  price_floor: number | null;
  price_ceiling: number | null;
  historical_units_outside_current_rule: number;
  synthetic_scenarios: string[];
  historical_evidence_days: number;
  validated_for_real_bidding: false;
  confidence_status: string;
  assumption: string;
  pmss_write_performed: false;
  pmss_clearing_executed: false;
  pmss_counterfactual_verified: false;
  safe_for_live_submission: false;
};
