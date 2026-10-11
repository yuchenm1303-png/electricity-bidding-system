# Three-profile bidding strategy research (local only)

`POST /api/pmss/strategy-trio` reuses the existing PMSS snapshot parser,
lossless DC nodal dispatch and optional 24-hour DC+UC MILP. It never
connects to or executes teacher PMSS endpoints, and cannot submit offers.

## Input

The request includes a sanitized historical snapshot, **mapped DC grid** and
target generator. It may include independent physical records. The same
request-size, sensitive-key, and allowed-snapshot filters used by the PMSS
analysis API apply.

```json
{
  "snapshot": {
    "unitTree": [],
    "unitBids": {},
    "marketSystem": {},
    "demandForecastMw": [],
    "forecastSource": "...",
    "historicalBacktestOnly": true,
    "dcNetwork": {}
  },
  "target_unit_id": "G1",
  "peer_price_deviation": 0.05
}
```

This is a **shape illustration**, not executable data. Use an authorized
complete 24-hour snapshot with the corresponding 39-node network, if
available. The API does not fabricate missing rows. In particular,
`dcNetwork.hourlyDemandMw` must reconcile with the aggregate load for all
24 hours and the unit-to-bus mapping must match the snapshot exactly.

For an optional integrated physics screening add all of:
`technical` (an exact `ThermalConstraints` record for **every** generator),
`technical_source` (`synthetic` or `course_verified_by_user`),
`technical_source_description`, and (for `course_verified_by_user`)
`technical_lineage` containing matching case-bound, field-level
source/units/value references. Uploaded references are user assertions, not
independent evidence of the teacher simulator's rules.

## Algorithm

1. Start bids at the recorded running-cost proxy and current market price
   floor. Generate bounded markup and increasing five-segment supply-curve
   variants; strictly discard prices outside the snapshotted rule, duplicates
   and all-zero offers. The original historical bid is **not** a new candidate.
2. Solve 24-hour nodal, line-limited DC dispatch in three equally weighted
   synthetic peer-price stress scenarios (default ±5%). These weights are
   *sensitivity bookkeeping*, not future event probabilities.
3. Select distinct candidates for **收益优先** (expected DC margin),
   **均衡** (55% expected plus 45% downside DC margin), and **稳健**
   (10% expected plus 90% downside). Each profile is best *among screened
   legal candidates*, subject to distinctness, not a globally optimal bid.
4. Mark a full-capacity dispatch sustained for 24 hours as requiring
   manual review. Without complete physical constraints, all profiles retain
   `UNKNOWN_MISSING_TECHNICAL_INPUTS`, with no profitability or physical
   certification. With complete records, each chosen profile runs the
   existing 24-hour DC+UC MILP including ramp, minimum on/off,
   start/stop and transition cost; infeasibility, solver non-proof and
   integrated all-day full output remain explicit statuses.

`local_candidate_usable` only means the **local** physical scenario solved,
with no flagged persistent full-output anomaly. It does **not** authorize
PMSS submission. `safe_for_live_submission`, `real_pmss_clearing`,
`pmss_write_performed` and `pmss_clearing_executed` are always false.

## Boundaries

These are read-only, historical-input counterfactuals using **lossless DC**
nodal dual prices, not teacher PMSS SCUC/SCED, AC losses, reserve or actual
settlement. Future loads, peer responses and actual technical definitions
are not independently validated. A common 24-hour offer curve is **not**
a commitment to run the generator at maximum capacity for 24 hours.
Avoid reporting modeled margins as realized PMSS earnings.

## Validation

`pytest -q tests/test_strategy_trio.py tests/test_pmss_strategy_trio_api.py`
and `ruff check app/pmss_api.py src/powerbid/strategy_trio.py tests/test_strategy_trio.py tests/test_pmss_strategy_trio_api.py`.
Full repo CI also runs on the PR.
