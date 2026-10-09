# Historical observed-zero masking can expose LP tie-selection, not commitment

**Research-only / no teacher PMSS write, clearing, or candidate-bid verification.**

The existing `replay_zero_output_restriction` test is explicitly **ex post**:
it uses same-day *actual observed* zero MW to add upper-bound restrictions.
It is **not** a valid predictor or a verified unit on/off state.

A crucial difference is now measured rather than assumed:

- Zero-output masks are counted only in hours where at least one observed-zero
  unit exists; hours with no zero-output unit are reported separately.
- When a baseline DC solution already gives zero output within 1e-6 MW
  numerical tolerance to every generator
  in the observed-zero set, it remains feasible under that masking set.
- If recomputing still changes generator output, this is a **nonbinding mask
  redispatch**. A reduced historical MAE alone cannot be attributed to an
  identified ramp or commitment constraint. Competing equal-cost dispatch
  and solver numerical conventions must be investigated first.
- `maxAbsolutePrimaryBidCostGap` records the primary bid-cost difference
  to help distinguish numerical effects. A tiny gap is not proof of PMSS
  clearing rules, and masking never demonstrates true causal attribution.

Use only earlier-dated training snapshots:

```bash
python scripts/report_pmss_nonbinding_mask.py \
  --holdout-start-date 2025-09-03 \
  --output /private/pmss-training-nonbinding.json \
  /private/2025-09-01.json /private/2025-09-02.json
```

The program rejects input snapshots dated on or after the declared holdout
date and never reads holdout PMSS outcomes. It generates a new mode-`0600`
report with only aggregate hourly deltas, counts and dates, not raw unit IDs
or offers. It cannot certify a new bidding strategy.

The next legitimate modeling task is to verify the physical semantics of
the PMSS calculation codes and initial operating state **using authorized
evidence**, then supply complete verified `ThermalConstraints` to the existing
24-hour joint MILP. Do **not** infer an on/off mapping from numeric code
`ifConRamp=1` or interpret `initialState=10` without documentation.

Older reports of "masked historical fit improvement" must be interpreted
with the new nonbinding-redispatch annotation, not promoted to UC gains.
