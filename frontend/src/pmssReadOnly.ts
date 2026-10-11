import type { PMSSInspection } from "./types";

/**
 * Contract owned by the authorized PMSS read-only backend (window A).
 * Browser only talks to same-origin PowerBid; never to PMSS/VPN directly.
 * 404/401/403 are hard failures, not triggers for synthetic data.
 */
export type PMSSProjectRef = { project_id: string; name: string };
export type PMSSCaseRef = { case_date: string; label?: string };

const PREFIX = import.meta.env.BASE_URL + "api/pmss/read-only/";
const isObject = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const datePattern = /^\d{4}-\d{2}-\d{2}$/;

/** Bound the entire request, including response JSON parsing, to avoid a permanent spinner. */
async function readOnlyGet(path: string, signal: AbortSignal): Promise<unknown> {
  const timeout = new AbortController();
  const forwardAbort = () => timeout.abort();
  if (signal.aborted) timeout.abort();
  else signal.addEventListener("abort", forwardAbort, { once: true });
  const timer = window.setTimeout(() => timeout.abort(), 12000);
  try {
    const response = await fetch(PREFIX + path, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: timeout.signal,
      redirect: "error",
    });
    if (!response.ok) {
      if (response.status === 404 || response.status === 501) {
        throw new Error("授权只读数据接口尚未启用，请联系管理员。");
      }
      if (response.status === 401) {
        throw new Error("PowerBid 登录已失效，请重新登录。");
      }
      if (response.status === 403) {
        throw new Error("当前账号尚未获授权读取该学校工程，其他报价分析功能仍可使用。");
      }
      if (response.status === 502 || response.status === 503 || response.status === 504) {
        throw new Error("PowerBid 数据服务暂时不可用（HTTP " + response.status + "），请稍后重试。VPN 正常不代表应用网关正常。");
      }
      throw new Error("只读数据接口暂不可用（HTTP " + response.status + "）。");
    }
    if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
      throw new Error("只读接口未返回 JSON，不能将登录页识别为市场数据。");
    }
    return await response.json() as unknown;
  } catch (error) {
    if (signal.aborted) throw error;
    if (timeout.signal.aborted) {
      throw new Error("读取工程数据超过 12 秒，请稍后重试；无需重新连接学校 VPN。");
    }
    if (error instanceof TypeError) {
      throw new Error("无法连接到 PowerBid 数据服务，请检查网站网络后重试。");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
    signal.removeEventListener("abort", forwardAbort);
  }
}

export async function getPMSSProjects(signal: AbortSignal): Promise<PMSSProjectRef[]> {
  const payload = await readOnlyGet("projects", signal);
  if (!isObject(payload) || !Array.isArray(payload.projects)) {
    throw new Error("工程列表接口格式不兼容。");
  }
  return payload.projects.map((item: unknown) => {
    if (!isObject(item) || typeof item.project_id !== "string" ||
        !item.project_id.trim() || item.project_id.length > 128 ||
        typeof item.name !== "string" || !item.name.trim()) {
      throw new Error("工程列表包含无效工程标识。");
    }
    return { project_id: item.project_id, name: item.name };
  });
}

export async function getPMSSCases(projectId: string, signal: AbortSignal): Promise<PMSSCaseRef[]> {
  if (!projectId || projectId.length > 128) throw new Error("无效工程。");
  const payload = await readOnlyGet("cases?project_id=" + encodeURIComponent(projectId), signal);
  if (!isObject(payload) || !Array.isArray(payload.cases)) {
    throw new Error("案例日期接口格式不兼容。");
  }
  return payload.cases.map((item: unknown) => {
    if (!isObject(item) || typeof item.case_date !== "string" ||
        !datePattern.test(item.case_date)) throw new Error("案例日期无效。");
    return {
      case_date: item.case_date,
      label: typeof item.label === "string" ? item.label : undefined,
    };
  });
}

export async function getPMSSSnapshot(
  projectId: string, date: string, signal: AbortSignal,
): Promise<Record<string, unknown>> {
  if (!projectId || projectId.length > 128 || !datePattern.test(date)) {
    throw new Error("必须明确选择有效工程和案例日期。");
  }
  const query = "snapshot?project_id=" + encodeURIComponent(projectId) +
    "&case_date=" + encodeURIComponent(date);
  const payload = await readOnlyGet(query, signal);
  if (!isObject(payload) || payload.source_kind !== "authorized_pmss_read_only" ||
      payload.read_only !== true || payload.project_id !== projectId ||
      payload.case_date !== date || !isObject(payload.snapshot)) {
    throw new Error("只读快照缺少工程/日期/来源核验，不接受未证实的数据。");
  }
  const snapshot = payload.snapshot;
  if (snapshot.caseDate !== date ||
      !Array.isArray(snapshot.unitTree) || !isObject(snapshot.unitBids) ||
      !isObject(snapshot.marketSystem) || !Array.isArray(snapshot.demandForecastMw) ||
      snapshot.demandForecastMw.length !== 24) {
    throw new Error("只读快照缺少与所选日期一致的 24 小时市场模型。");
  }
  if (JSON.stringify(snapshot).length > 700_000) {
    throw new Error("服务端快照超过浏览器研究接口的安全限制。");
  }
  return snapshot;
}

/** Do not claim a historical PMSS result when inspection reports no coverage. */
export function describePMSSCoverage(inspection: PMSSInspection): string {
  const network = inspection.network;
  return network && network.price_coverage_points > 0
    ? "包含历史出清数据（仅对应原始报价）"
    : "仅有市场输入，未提供可核验的历史出清记录";
}
