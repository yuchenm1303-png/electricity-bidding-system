import type { Scenario, Settings, Report } from "./types";

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
    headers: { "Content-Type": "application/json" },
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
