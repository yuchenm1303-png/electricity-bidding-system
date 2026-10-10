import test from "node:test";
import assert from "node:assert/strict";
import {
  makePMSSBidProposal, proposalFromSurrogate, proposalFromNetworkRank,
  proposalAuditDocument,
} from "../src/pmssBiddingFlow.ts";

function caseInfo() {
  return {
    case_date: "2025-09-01",
    max_segments: 5,
    units: [{unit_id:"GEN-A", capacity_mw:100}],
    historical_bid_rule_audit: {price_floor:0, price_ceiling:1000},
  };
}
const blocks = [
  {start_power:0, end_power:20, price:100},
  {start_power:20, end_power:40, price:120},
  {start_power:40, end_power:60, price:140},
  {start_power:60, end_power:80, price:160},
  {start_power:80, end_power:100, price:180},
];

test("proposal keeps one shared 24h curve and fails closed on platform claims", () => {
  const original = blocks.map(x => ({...x}));
  const proposal = makePMSSBidProposal(caseInfo(), "GEN-A", "surrogate", original, "unit test");
  original[0].price = 777;
  assert.equal(proposal.segments[0].price, 100, "do not retain mutable source blocks");
  const audit = proposalAuditDocument(proposal);
  assert.equal(audit.startPeriod, 1);
  assert.equal(audit.endPeriod, 24);
  assert.equal(audit.shared24hCurve, true);
  assert.equal(audit.submittedToPMSS, false);
  assert.equal(audit.pmssClearingExecuted, false);
  assert.equal(audit.pmssCandidateResultVerified, false);
  assert.equal(audit.segments.length, 5);
});

test("surrogate and DC risk-ranked recommendations share the same handoff contract", () => {
  const inspection = caseInfo();
  const surrogate = proposalFromSurrogate(inspection, {
    target_unit_id:"GEN-A", recommended:{segments:blocks},
  });
  const ranked = proposalFromNetworkRank(inspection, {
    target_unit_id:"GEN-A", best_candidate:{
      name:"rule-compliant test policy",
      price_blocks:blocks.map(b=>[b.start_power,b.end_power,b.price]),
    },
  });
  assert.equal(surrogate.source, "surrogate");
  assert.equal(ranked.source, "network-risk");
  assert.deepEqual(ranked.segments, surrogate.segments);
  assert.equal(ranked.platformSubmitted, false);
});

test("wrong case identity, missing date, bad segments and illegal prices are blocked", () => {
  assert.throws(()=>makePMSSBidProposal(caseInfo(), "OTHER", "surrogate", blocks, "x"),/机组/);
  assert.throws(()=>makePMSSBidProposal({...caseInfo(),case_date:""}, "GEN-A", "surrogate", blocks, "x"),/日期/);
  assert.throws(()=>makePMSSBidProposal(caseInfo(), "GEN-A", "surrogate", [
    {...blocks[0],price:1001},...blocks.slice(1),
  ], "x"),/规则/);
  assert.throws(()=>makePMSSBidProposal(caseInfo(), "GEN-A", "surrogate", [
    blocks[0], {...blocks[1],start_power:21}, ...blocks.slice(2),
  ], "x"),/连续性/);
  assert.throws(()=>makePMSSBidProposal(caseInfo(), "GEN-A", "surrogate", [
    ...blocks.slice(0,-1), {...blocks[4],end_power:101},
  ], "x"),/容量/);
  assert.throws(()=>makePMSSBidProposal(caseInfo(), "GEN-A", "surrogate", [
    {...blocks[0],price:NaN},...blocks.slice(1),
  ], "x"),/规则/);
});
