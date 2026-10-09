# Offline PMSS generator scene evidence + original-bid temporal audit

Use the **already authorized, privately saved** calculation response and
strictly earlier-dated historical snapshots. Do not log in to PMSS or call
any read/write endpoint for this tool.

```bash
python scripts/report_pmss_uc_training.py \
  --scene-capture /private/read-only-scene.json \
  --holdout-start-date 2025-09-03 \
  --output /private/training-uc-source-evidence.json \
  /private/history-2025-09-01.json /private/history-2025-09-02.json
```

Only a complete HTTP 200 / **business T200** calculation source is accepted.
Its ten scenario `unitId` values must exactly match the ten bidding unit IDs
in both training cases, with no duplicates and a single consistent scene ID.
This establishes **structural identity**, not signed same-case provenance or
physical field semantics. An unavailable independent initial-state GET is
reported as a blocker rather than filled with invented initial states.

Each training date additionally compares adjacent hourly **observed generation
MW changes** with the existing standalone original-bid DC replay. We report
anonymous max and p95 changes, hourly difference MAE, and positive/zero crossing
counts. These are descriptive; zero MW does **not** verify an offline machine
when minimum output may be zero. An observed generation increase does not
establish the physical ramp-rate limit, and zero/positive crossings are not
verified starts or stops.

All six core commitment evidence blockers remain explicit. No complete
`ThermalConstraints` records are produced. Training snapshots dated on or
after the declared holdout start are rejected **before** any historical
predictions are computed. All private inputs and the non-overwriting `0600`
summary remain on the authorized machine and do not go to GitHub. No new
bidding strategy, counterfactual price, PMSS clearing, or settlement is claimed.
