import type { Scenario, Settings, Report, PMSSInspection, PMSSOptimization, PMSSNetworkComparison, PMSSNetworkRank, PMSSCandidateDispatchRange, PMSSJointMwhRange, PMSSHoldoutReview } from "./types";

const BASE = import.meta.env.BASE_URL;

async function unpack<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = data?.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((issue: { msg?: string }) => issue.msg ?? "参数有误").join("；")
        : "请求失败，请稍后重试";
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}
export const loadScenario = async () => unpack<Scenario>(await fetch(BASE + "api/scenario"));
export const runOptimization = async (settings: Settings) =>
  unpack<Report>(await fetch(BASE + "api/optimize", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-PowerBid-Request": "1" },
    body: JSON.stringify(settings),
  }));
export const fromScenario = (scenario: Scenario): Settings => ({
  demand_mw: scenario.demand_mw,
  interval_hours: scenario.interval_hours,
  target_unit_id: scenario.target_unit_id,
  offers: scenario.offers.map(offer => ({ ...offer })),
  start: 180,
  stop: 400,
  step: 10,
  mode: "single",
  engine: "uniform",
  demand_uncertainty: 0.15,
  competitor_uncertainty: 0.15,
  risk_aversion: 0.35,
  tail_fraction: 0.25,
});

export async function inspectPMSS(snapshot: Record<string, unknown>): Promise<PMSSInspection> {
  return unpack<PMSSInspection>(await fetch(BASE + "api/pmss/inspect", {
    method: "POST", headers: { "Content-Type": "application/json", "X-PowerBid-Request": "1" },
    body: JSON.stringify({ snapshot }),
  }));
}
export async function optimizePMSS(
  snapshot: Record<string, unknown>,
  target_unit_id: string,
  candidate_prices: number[],
  iterations: number,
): Promise<PMSSOptimization> {
  return unpack<PMSSOptimization>(await fetch(BASE + "api/pmss/optimize", {
    method: "POST", headers: { "Content-Type": "application/json", "X-PowerBid-Request": "1" },
    body: JSON.stringify({ snapshot, target_unit_id, candidate_prices, iterations }),
  }));
}

export async function evaluatePMSSNetwork(
  snapshot: Record<string, unknown>,
  target_unit_id: string,
  recommended_segments: {start_power: number; end_power: number; price: number}[],
): Promise<PMSSNetworkComparison> {
  return unpack<PMSSNetworkComparison>(await fetch(BASE + "api/pmss/network-evaluate", {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-PowerBid-Request": "1"},
    body: JSON.stringify({snapshot, target_unit_id, recommended_segments}),
  }));
}

export async function rankPMSSNetwork(
  snapshot: Record<string, unknown>,
  target_unit_id: string,
  risk_aversion: number,
  peer_price_deviation: number,
): Promise<PMSSNetworkRank> {
  return unpack<PMSSNetworkRank>(await fetch(BASE + "api/pmss/network-rank", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-PowerBid-Request": "1" },
    body: JSON.stringify({ snapshot, target_unit_id, risk_aversion, peer_price_deviation }),
  }));
}


/** Local DC optimal-face bounds, not a PMSS clearing or price prediction. */
export async function analyzePMSSCandidateDispatch(
  snapshot: Record<string, unknown>,
  target_unit_id: string,
  recommended_segments: {start_power: number; end_power: number; price: number}[],
): Promise<PMSSCandidateDispatchRange> {
  return unpack<PMSSCandidateDispatchRange>(
    await fetch(BASE + "api/pmss/network-dispatch-range", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-PowerBid-Request": "1"},
      body: JSON.stringify({snapshot, target_unit_id, recommended_segments}),
    }),
  );
}


/** Joint 24h DC+UC research only; refuses absent or unverified-source machine data. */
export async function analyzePMSSJointCandidateMwh(
  snapshot: Record<string, unknown>,
  target_unit_id: string,
  recommended_segments: {start_power: number; end_power: number; price: number}[],
  technical: Record<string, unknown>,
  technical_lineage: Record<string, unknown>,
  technical_source_description: string,
): Promise<PMSSJointMwhRange> {
  return unpack<PMSSJointMwhRange>(
    await fetch(BASE + "api/pmss/network-joint-mwh-range", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-PowerBid-Request": "1"},
      body: JSON.stringify({
        snapshot, target_unit_id, recommended_segments, technical, technical_lineage,
        technical_source: "course_verified_by_user",
        technical_source_description,
        terminal_mode: "carryover",
      }),
    }),
  );
}


/** Pure local audit of an anonymized report; no PMSS connection or write. */
export async function inspectPMSSHoldoutReport(
  report: Record<string, unknown>,
): Promise<PMSSHoldoutReview> {
  return unpack<PMSSHoldoutReview>(
    await fetch(BASE + "api/pmss/holdout-gate", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-PowerBid-Request": "1"},
      body: JSON.stringify({report}),
    }),
  );
}
