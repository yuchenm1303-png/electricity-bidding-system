import type { PMSSInspection, PMSSOptimization, PMSSNetworkRank } from "./types";

export type PMSSBidSegment = PMSSOptimization["recommended"]["segments"][number];

/**
 * A deliberately local, human-review proposal. No PMSS submission identifier
 * exists here; historical observations cannot authenticate this proposal.
 */
export type PMSSBidProposal = {
  caseDate: string;
  targetUnitId: string;
  source: "surrogate" | "network-risk";
  strategyLabel: string;
  segments: PMSSBidSegment[];
  shared24hCurve: true;
  platformSubmitted: false;
  pmssCleared: false;
};

export function makePMSSBidProposal(
  inspection: PMSSInspection,
  targetUnitId: string,
  source: PMSSBidProposal["source"],
  segments: PMSSBidSegment[],
  strategyLabel: string,
): PMSSBidProposal {
  const unit = inspection.units.find(item => item.unit_id === targetUnitId);
  if (!unit) throw new Error("目标机组与当前 PMSS 案例不一致");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(inspection.case_date)) {
    throw new Error("案例缺少 YYYY-MM-DD 日期，无法安全建立报价交接");
  }
  if (inspection.max_segments < 1 || inspection.max_segments > 5 ||
      segments.length < 1 || segments.length > inspection.max_segments) {
    throw new Error("报价段数不符合当前 PMSS 案例市场规则");
  }
  const floor = inspection.historical_bid_rule_audit.price_floor ?? 0;
  const ceiling = inspection.historical_bid_rule_audit.price_ceiling ?? 10000;
  let previousEnd: number | null = null;
  for (const segment of segments) {
    const {start_power, end_power, price} = segment;
    if (![start_power, end_power, price].every(Number.isFinite) ||
        start_power < 0 || end_power <= start_power ||
        (previousEnd !== null && Math.abs(previousEnd - start_power) > 1e-7) ||
        end_power > unit.capacity_mw + 1e-7 ||
        price < floor || price > ceiling) {
      throw new Error("候选报价超出机组容量、价格规则或分段连续性限制");
    }
    previousEnd = end_power;
  }
  return {
    caseDate: inspection.case_date, targetUnitId, source,
    strategyLabel, segments: segments.map(segment => ({...segment})),
    shared24hCurve: true, platformSubmitted: false, pmssCleared: false,
  };
}

export function proposalFromSurrogate(
  inspection: PMSSInspection, analysis: PMSSOptimization,
): PMSSBidProposal {
  return makePMSSBidProposal(
    inspection, analysis.target_unit_id, "surrogate",
    analysis.recommended.segments, "单区域五段坐标搜索",
  );
}

export function proposalFromNetworkRank(
  inspection: PMSSInspection, ranked: PMSSNetworkRank,
): PMSSBidProposal {
  return makePMSSBidProposal(
    inspection, ranked.target_unit_id, "network-risk",
    ranked.best_candidate.price_blocks.map(([start_power, end_power, price]) =>
      ({start_power, end_power, price})),
    ranked.best_candidate.name,
  );
}

/** Download only a local audit artifact; never an official PMSS payload. */
export function proposalAuditDocument(proposal: PMSSBidProposal) {
  return {
    source: "POWERBID_LOCAL_CANDIDATE_NOT_PMSS_CLEARED",
    caseDate: proposal.caseDate,
    targetUnitId: proposal.targetUnitId,
    marketType: "DA",
    strategySource: proposal.source,
    strategyLabel: proposal.strategyLabel,
    shared24hCurve: true,
    startPeriod: 1, endPeriod: 24,
    manualReviewOnly: true,
    submittedToPMSS: false,
    pmssClearingExecuted: false,
    pmssCandidateResultVerified: false,
    segments: proposal.segments.map((segment, index) => ({
      segmentOrder: index + 1,
      startPower: segment.start_power,
      endPower: segment.end_power,
      price: segment.price,
    })),
  };
}
