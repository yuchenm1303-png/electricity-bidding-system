# PMSS strategy guard · chronological research-only verification

This feature is deliberately **not** a bid approval system. It uses the
existing 24-hour original-offer DC market replay and PMSS historical
observations to assess model errors, then separately recomputes hypothetical
candidate curves under the **local DC surrogate**. No API in this feature
submits a bid, calls the teacher's clearing service, or authenticates a PMSS
counterfactual.

## Historical evidence and limits

The three authorized September 2025 cases already documented in
[PMSS_THREE_DAY_RESEARCH_2025-09.md](PMSS_THREE_DAY_RESEARCH_2025-09.md)
were collected on the trusted server; the protected raw snapshots are
**not checked into this repository**. Their publicly documented aggregate
errors are:

| Day | Original-offer DC dispatch MAE (MW) | Nodal price MAE (PMSS unit unverified) | Absolute line-flow MAE (MW) |
|---|---:|---:|---:|
| 2025-09-01 | 47.102 | 397.370 | 43.343 |
| 2025-09-02 | 17.954 | 13.730 | 17.043 |
| 2025-09-03 | 26.193 | 9.778 | 23.172 |

The original offers on September 2 and 3 were reported identical.
**Distinct dates are not three independent bid strategies.** The guard
computes normalized bid-curve digests that ignore scope metadata, dates
and IDs for the same-day study, so repeated bids cannot accidentally
inflate the apparent independent evidence.

The local historical validator replays **the original** bids, never a
new candidate's supposed teacher outcome. The last chronological day
is held out; training-only candidate scores are frozen before its modeled
diagnostics are recorded. The original-bid error gate uses configurable
course-project *research tolerances* (dispatch MAE 20 MW, nodal price MAE
50 in PMSS-reported units, 100% observed coverage) that are **not**
teacher-approved quality standards. The published September 2025 held-out
dispatch MAE of 26.193 MW exceeds this default tolerance; this does not
support a real-world strategy recommendation.

## Ranking and gates

Candidates from Window A can use either `price_blocks: [[start, end, price],...]`,
`segments: [{start_power, end_power, price},...]`, or
`recommended_segments`. An optional `id` / `strategy_id` and required
`name` are preserved. Supplied score/profit fields are completely ignored.

The engine recomputes at most six curves against three to five complete
dated snapshots and their verified DC network definitions. The score is
**relative among candidates on training dates only**, with weights:

| Item | Points | Interpretation |
|---|---:|---|
| Mean local DC margin relative rank | 30 | Normalized within this batch; not real profit |
| Worst training day local DC margin relative rank | 25 | Prefer less fragile candidates |
| Inter-date local DC margin stability | 25 | Penalize differences between training days |
| Price ceiling distance | 20 | Halve this component for near-ceiling quotes |

Tied margins receive **zero relative advantage**; an arbitrarily large
model result by itself cannot establish actual performance. No historical
teacher nodal prices are substituted for candidate prices or used to
compute counterfactual candidate profit.

Hard blockers include: non-contiguous/out-of-rule/over-capacity offers,
all-zero bid prices, decreasing cumulative prices, curves that do not start
at zero, and 24 hours of 100%-capacity dispatch in any studied local
case. Price-ceiling proximity, low offered capacity, or negative modeled
training margin become explicit warnings. The model's missing verified
startup, ramp, minimum up/down, reserve and AC constraints are flagged;
physical feasibility must never be inferred from a DC result.

Research shortlist admission requires all candidate rules, acceptable
original-offer *held-out* model fit, two different **training original bid
curves**, and no holdout original offer curve reused from training.
A shortlist is only a **local research comparison**, not a submission
authorization. `recommended_for_real_pmss` is always null,
`live_bid_allowed` is always false, and
`real_pmss_candidate_profit_verified` is always false. Even a
`C2_HISTORICAL_ORIGINAL_BID_FIT_ONLY` model grade cannot verify a new bid.

## How to run

On an authorized private machine with existing historical snapshot files:

```bash
python scripts/report_pmss_strategy_guard.py \
  --target-unit-id YOUR_UNIT_ID \
  --candidates /private/candidate-curves.json \
  --output /private/strategy-risk.json \
  /private/2025-09-01.json \
  /private/2025-09-02.json \
  /private/2025-09-03.json
```

The script refuses existing outputs and writes aggregate-only reports with
mode `0600`. No private PMSS files or sensitive identifiers need to be
committed. The React backend also exposes
`POST /api/pmss/strategy-guard` with payload
`{"history_cases":[<sanitized snapshot objects>],"candidates":[...],"target_unit_id":"..."}`.
The endpoint uses existing recursion-based secret checks, request size
caps, bounded case/candidate counts and a shared network compute lock.

For tests: `pytest -q tests/test_pmss_strategy_guard.py` and `ruff check .`.
The tests use **synthetic two-bus** cases. They do not claim to have
rerun private September cases in CI.

## Unresolved evidence for trustworthy submission

1. Verify actual PMSS market/price/settlement units and physical
   constraints (UC ramp, on/off, minimum operating output, startup cost).
2. Obtain more genuinely independent historical bid curves and
   separately held-out dates; three case dates alone provide weak support.
3. Obtain authenticated *new-candidate* submission/result pairs with
   permission, and reconcile observed income with costs to compute net
   earnings. Existing historical original bids cannot supply those pairs.
4. Keep live bidding manually reviewed until a separate, audited
   authorization and physical-completeness process is explicitly built.
