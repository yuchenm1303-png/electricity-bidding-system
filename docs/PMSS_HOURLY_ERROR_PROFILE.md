# Historical hourly and cohort-maximum error diagnostic (private)

For local research with three authorized historical PMSS snapshots only, run:

```bash
python scripts/report_pmss_hourly_errors.py \
  --max-unit-mae-mw 20 --max-nodal-price-mae 50 --holdout-days 1 \
  --output /private/research-hourly-profile.json \
  /private/day-1.json /private/day-2.json /private/day-3.json
```

The thresholds above are **illustrative researcher assumptions**, not a standard
for market-model certification. Dates are sorted chronologically and the last
date is evaluated by `judge_historical_model` as the held-out day.

This tool computes all 24 hourly MAEs and largest individual absolute errors.
It also checks each generator, node, and line over all hours before publishing
only the **largest among their daily errors**, without IDs, offers, raw
prices, scopes, paths or source authentication. Missing point observations are
represented as `null`, never silently counted as zero. The flow comparison
uses **absolute flow magnitudes**, not signed line directions.

A written output is a new file with mode `0600` and is never put in the
public repository. The source snapshots must stay in private storage. Not a
real PMSS candidate-bid clearing or verification of earnings. The reason for
specific price observations (including 2025-09-01 h11/h17) remains unproven;
this diagnostic reports deviations without inferring a market price cap.
