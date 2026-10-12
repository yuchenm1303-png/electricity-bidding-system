import test from "node:test";
import assert from "node:assert/strict";
import { buildSmartBidProfiles, suggestedSmartProfile, buildSmartTrioProfiles, suggestedGuardedProfile } from "../src/pmssSmartBid.ts";

const blocks = (...prices) => prices.map((price, i) => [i * 20, (i + 1) * 20, price]);
const inspection = () => ({
  case_date: "2025-09-01", historical_only: true, dc_grid_available: true,
  max_segments: 5, units: [{unit_id: "GEN-A", capacity_mw: 100}],
  historical_bid_rule_audit: {price_floor: 0, price_ceiling: 1000},
});
const makeCurve = (name, expected, score, downside, prices) => ({
  name, expected_margin: expected, score, downside_margin: downside,
  worst_margin: downside - 1, expected_accepted_mwh: 160,
  price_blocks: blocks(...prices),
});
const rank = candidates => ({
  target_unit_id: "GEN-A", eligible_candidates: candidates,
  best_candidate: candidates[0], pmss_write_performed: false,
  pmss_clearing_executed: false, pmss_counterfactual_verified: false,
  validated_for_real_bidding: false, safe_for_live_submission: false,
  confidence_status: "RESEARCH_ONLY_NOT_OUT_OF_SAMPLE_VALIDATED",
  historical_evidence_days: 1,
});

test("profiles are independent legal backend curves, not invented or copied strategies", () => {
  const input = [
    makeCurve("expected best", 100, 50, 10, [100,120,140,160,180]),
    makeCurve("balanced best", 90, 100, 30, [120,140,160,180,200]),
    makeCurve("downside best", 70, 70, 60, [140,160,180,200,220]),
  ];
  const actual = buildSmartBidProfiles(inspection(),rank(input));
  assert.deepEqual(actual.map(x => x.id), ["revenue","balanced","defensive"]);
  assert.deepEqual(actual.map(x => x.candidate.name), input.map(x => x.name));
  assert.equal(suggestedSmartProfile(actual).id, "balanced");
  for (const p of actual) {
    assert.equal(p.proposal.platformSubmitted, false);
    assert.equal(p.proposal.pmssCleared, false);
    assert.equal(p.proposal.segments.length, 5);
    assert.equal(p.proposal.shared24hCurve, true);
  }
});

test("single distinct curve never fills three profiles", () => {
  const original = makeCurve("one",10,10,10,[10,20,30,40,50]);
  const actual = buildSmartBidProfiles(inspection(), rank([original,{...original,name:"copy"}]));
  assert.equal(actual.length,1);
  assert.equal(actual[0].id,"revenue");
});

test("all-zero, all-ceiling, invalid MW, NaN and out-of-rule prices are excluded", () => {
  const zero = makeCurve("zero",1000,100,100,[0,0,0,0,0]);
  const ceiling = makeCurve("ceiling",1000,100,100,[1000,1000,1000,1000,1000]);
  const invalid = makeCurve("MW invalid",1000,100,100,[10,20,30,40,50]);
  invalid.price_blocks[1][0] = 22;
  const nan = makeCurve("NaN",NaN,100,100,[10,20,30,40,50]);
  const tooHigh = makeCurve("over cap",100,100,100,[100,200,300,400,1001]);
  assert.deepEqual(buildSmartBidProfiles(inspection(),rank([zero,ceiling,invalid,nan,tooHigh])), []);
});

test("unverified or mismatched context fails closed", () => {
  const c = makeCurve("normal",3,3,3,[10,20,30,40,50]);
  assert.deepEqual(buildSmartBidProfiles(inspection(),{...rank([c]),safe_for_live_submission:true}),[]);
  assert.deepEqual(buildSmartBidProfiles(inspection(),{...rank([c]),pmss_clearing_executed:undefined}),[]);
  assert.deepEqual(buildSmartBidProfiles(inspection(),{...rank([c]),target_unit_id:"OTHER"}),[]);
  assert.deepEqual(buildSmartBidProfiles({...inspection(),historical_only:false},rank([c])),[]);
  assert.deepEqual(buildSmartBidProfiles({...inspection(),dc_grid_available:false},rank([c])),[]);
  assert.equal(suggestedSmartProfile([]),null);
});

const trio = () => ({
  target_unit_id: "GEN-A", study_only: true,
  real_pmss_clearing: false, safe_for_live_submission: false,
  pmss_write_performed: false, pmss_clearing_executed: false,
  candidates: [
    {profile: "收益优先", policy_name: "DC-profit", price_blocks: blocks(210,220,230,240,250),
      expected_dc_margin: 100, downside_dc_margin: 30, worst_dc_margin: 15,
      expected_dc_mwh: 900, profile_score: 94, warnings: []},
    {profile: "均衡", policy_name: "DC-balanced", price_blocks: blocks(220,240,260,280,300),
      expected_dc_margin: 92, downside_dc_margin: 52, worst_dc_margin: 31,
      expected_dc_mwh: 800, profile_score: 87, warnings: []},
    {profile: "稳健", policy_name: "DC-risk", price_blocks: blocks(240,260,280,300,320),
      expected_dc_margin: 80, downside_dc_margin: 65, worst_dc_margin: 47,
      expected_dc_mwh: 740, profile_score: 83, warnings: []},
  ],
});
const guarded = (okIds = ["均衡"]) => ({
  status: "HISTORICAL_ONLY_LOCAL_STRATEGY_RESEARCH",
  pmss_write_performed: false, pmss_clearing_executed: false,
  recommended_for_real_pmss: null,
  model_confidence_grade: "INDEPENDENT_HISTORICAL_RESEARCH_ONLY",
  candidates: trio().candidates.map(row => ({
    candidate_id: row.profile, research_shortlist_admitted: okIds.includes(row.profile),
    live_bid_allowed: false, real_pmss_candidate_profit_verified: false,
    hard_blockers: okIds.includes(row.profile) ? [] : ["UNCALIBRATED"],
    risk_warnings: [], score_training_only_0_to_100: 48,
  })),
  training_case_dates: ["2025-09-01","2025-09-02"],
  untouched_holdout_case_dates: ["2025-09-03"],
});

test("A candidates are displayed, B alone controls research recommendation", () => {
  const untested = buildSmartTrioProfiles(inspection(), trio(), null);
  assert.equal(untested.length, 3);
  assert.equal(suggestedGuardedProfile(untested), null);
  assert.ok(untested.every(x => x.researchAdmitted === false));
  const screened = buildSmartTrioProfiles(inspection(), trio(), guarded());
  assert.equal(screened.length, 3);
  assert.equal(suggestedGuardedProfile(screened)?.id, "balanced");
  assert.equal(screened.find(x => x.id === "revenue")?.researchAdmitted, false);
  assert.equal(screened[1].proposal.platformSubmitted, false);
});

test("B blocks all proposals, never invent a fallback recommendation", () => {
  const blocked = buildSmartTrioProfiles(inspection(), trio(), guarded([]));
  assert.equal(blocked.length, 3);
  assert.equal(suggestedGuardedProfile(blocked), null);
  assert.ok(blocked.every(x => x.riskBlockers?.includes("UNCALIBRATED")));
});

test("A/B provenance mismatch and fabricated duplicate curves fail closed", () => {
  assert.deepEqual(buildSmartTrioProfiles(inspection(), {...trio(),pmss_write_performed:true},guarded()),[]);
  assert.deepEqual(buildSmartTrioProfiles(inspection(),trio(),
    {...guarded(),recommended_for_real_pmss:"fake"}),[]);
  const copy = trio();
  copy.candidates[1].price_blocks = copy.candidates[0].price_blocks;
  assert.equal(buildSmartTrioProfiles(inspection(),copy,guarded()).length,2);
  const zeros = trio();
  zeros.candidates[0].price_blocks = blocks(0,0,0,0,0);
  assert.equal(buildSmartTrioProfiles(inspection(),zeros,guarded()).length,2);
});
