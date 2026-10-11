import type { PMSSInspection, PMSSNetworkRank, PMSSRankedCurve } from "./types";
import { makePMSSBidProposal, type PMSSBidProposal } from "./pmssBiddingFlow";

export type SmartProfileId = "revenue" | "balanced" | "defensive";
export type SmartBidProfile = {
  id: SmartProfileId;
  title: string;
  subtitle: string;
  rationale: string;
  candidate: PMSSRankedCurve;
  proposal: PMSSBidProposal;
};

/** Adapter for the existing network-rank output. No strategy is synthesized here. */
export function buildSmartBidProfiles(
  inspection: PMSSInspection,
  ranked: PMSSNetworkRank | null,
): SmartBidProfile[] {
  if (!ranked) return [];
  if (ranked.pmss_write_performed !== false ||
      ranked.pmss_clearing_executed !== false ||
      ranked.pmss_counterfactual_verified !== false ||
      ranked.validated_for_real_bidding !== false ||
      ranked.safe_for_live_submission !== false) {
    // Refuse ambiguous provenance instead of silently calling the results "verified".
    return [];
  }
  if (!inspection.historical_only || !inspection.dc_grid_available ||
      !inspection.units.some(unit => unit.unit_id === ranked.target_unit_id)) return [];

  const unique = new Map<string, {candidate: PMSSRankedCurve; proposal: PMSSBidProposal}>();
  for (const candidate of ranked.eligible_candidates ?? []) {
    if (!candidate || !Array.isArray(candidate.price_blocks) ||
        ![candidate.score, candidate.expected_margin, candidate.downside_margin,
          candidate.worst_margin, candidate.expected_accepted_mwh].every(Number.isFinite)) continue;
    if (!candidate.price_blocks.every(block =>
      Array.isArray(block) && block.length === 3 && block.every(Number.isFinite))) continue;
    const prices = candidate.price_blocks.map(block => block[2]);
    const ceiling = inspection.historical_bid_rule_audit.price_ceiling;
    // Two obvious degenerate bidding patterns must never be surfaced as recommended.
    if (prices.every(price => price === 0) ||
        (ceiling !== null && prices.every(price => price >= ceiling))) continue;
    try {
      const proposal = makePMSSBidProposal(
        inspection, ranked.target_unit_id, "network-risk",
        candidate.price_blocks.map(([start_power, end_power, price]) =>
          ({start_power, end_power, price})),
        candidate.name,
      );
      const fingerprint = JSON.stringify(proposal.segments);
      if (!unique.has(fingerprint)) unique.set(fingerprint, {candidate, proposal});
    } catch {
      // Skip out-of-rule, discontinuous and invalid curves, even if the API calls them eligible.
    }
  }

  const pool = [...unique.values()];
  const claimed = new Set<string>();
  const definitions: {
    id: SmartProfileId; title: string; subtitle: string; rationale: string;
    order: (a: typeof pool[number], b: typeof pool[number]) => number;
  }[] = [
    {
      id: "revenue", title: "收益优先", subtitle: "收益代理指标较高",
      rationale: "在当前本地模拟情景中，优先比较期望边际收益；不代表老师平台的实际利润。",
      order: (a, b) => b.candidate.expected_margin - a.candidate.expected_margin,
    },
    {
      id: "balanced", title: "均衡策略", subtitle: "模型风险加权评分",
      rationale: "优先采用既有网络策略引擎的综合评分，兼顾模拟收益及下行情景。",
      order: (a, b) => b.candidate.score - a.candidate.score,
    },
    {
      id: "defensive", title: "稳健策略", subtitle: "下行情景优先",
      rationale: "优先比较模型下行情景边际收益，侧重降低模拟风险，而非保证实际安全。",
      order: (a, b) => b.candidate.downside_margin - a.candidate.downside_margin,
    },
  ];
  return definitions.flatMap(def => {
    const eligible = [...pool].filter(item => !claimed.has(JSON.stringify(item.proposal.segments)));
    eligible.sort((a, b) =>
      def.order(a, b) || a.candidate.name.localeCompare(b.candidate.name));
    const chosen = eligible[0];
    if (!chosen) return [];
    claimed.add(JSON.stringify(chosen.proposal.segments));
    return [{
      id: def.id, title: def.title, subtitle: def.subtitle,
      rationale: def.rationale, candidate: chosen.candidate, proposal: chosen.proposal,
    }];
  });
}

export function suggestedSmartProfile(profiles: SmartBidProfile[]): SmartBidProfile | null {
  // Research preference ONLY. This does not lift the model's submission prohibition.
  return profiles.find(item => item.id === "balanced") ??
    profiles.find(item => item.id === "defensive") ?? profiles[0] ?? null;
}
