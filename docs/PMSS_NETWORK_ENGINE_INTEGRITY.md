# PMSS Network Engine — physical-model and import contract (research only)

The existing PowerBid components remain the authority:

- `pmss_grid_bridge.sanitize_pmss_network` allowlists PMSS read-only
  Bus/Line/Unit and 24h DA load fields.
- `network_dispatch.network_from_dict` accepts the original **unchanged**
  `dcNetwork` DTO contract from window A: `buses`, `lines`,
  `unitBus`, `hourlyDemandMw`, `slackBus`, `baseMva`,
  `topologySource`, `demandSource`. No second PMSS data importer.
- `dc_clear_hour` is the existing hourly LP; `joint_clear_day` is
  the existing 24-hour integrated DC+UC MILP. Both now call an *independent*
  post-solve DC network audit. The non-extreme joint result additionally
  checks explicit on/start/stop states, Pmin/Pmax, ramps, initial state,
  minimum state durations and complete/carryover terminal interpretation.
  Extreme-MWh studies verify the projected solution's DC network too.

## Units and limits: do not mistake a numerical normalization for evidence

- All injections, line flows, ratings, ramps and generation are **MW**;
  every hourly interval is one hour. A day is 24 separate nodal loads,
  coupled only in the joint MILP by unit commitment/ramps.
- The line model is `f_MW = (baseMva / reactancePu) * (theta_from-theta_to)`.
  `reactancePu` must be a **positive per-unit relative reactance**, not
  an ohmic impedance or a Boolean/string; the bridge rejects explicit
  `xUnit=ohm` and unknown reactance unit markers. `limitMw` must be a
  positive finite **MW** rating, not an MVA rating silently renamed MW.
- The *legacy PMSS export does not independently certify reactance units or
  its physical baseMVA*. `baseMva=1` is solely a numerical angle scale:
  under a single common per-unit reactance base, unity taps and an ideal
  lossless DC network, any common positive base scales angles, while physical
  MW flows and lossless nodal duals are invariant. This statement does
  **not** hold as a validation of mixed impedances, ohms, nonunity/phase-
  shifting taps, MVA thermal ratings, losses or physical voltage angles.
  If the source contract changes, **halt rather than guess unit conversion**.
- Unit startup/shutdown costs are model assumptions in the same monetary
  unit as bid energy costs. True initial status, elapsed hours, hourly
  ramp rates, transition ramps, min up/down times and price conventions
  require independently verified PMSS/course evidence. Missing or
  ambiguous generator inputs must remain gated by
  `pmss_joint_research.assess_joint_readiness`; never derive them from
  historical accepted MW or raw PMSS fields with uncertain units.

## Solver postchecks

`audit_dc_solution` independently reconstructs mathematical bus angles from
a spanning tree, checks every line including cycle closure (KVL), per-bus MW
balance (KCL) and each directional thermal MW bound. A dispatch can satisfy
KCL yet fail KVL because of circulating cycle flow; it must be rejected.

`audit_joint_schedule` uses the actual MILP on/start/stop statuses, not
the `MW > 0` shortcut (wrong for online units with Pmin=0).
It independently checks initial-to-first-hour and interhour ramps,
startup/shutdown ramp limits, min state residence time and terminal mode.
The audits cannot establish that source physical parameters are accurate.

## Data handling and completion boundary

The public repository contains only code, test fixtures and documentation;
it intentionally does not ship the teacher's 39-node/46-line/10-unit
restricted data or login credentials. Existing controlled-host snapshots,
if authorized, may be loaded through the existing sanitized DTO without
schema migration. Historical observations do **not** prove that our
counterfactual quotations would clear the PMSS market.

**Verification needed before treating the teacher model as physically
calibrated:** documented x unit/common impedance base, MW versus MVA line
ratings, treatment of transformer tap/phase shift, source of all unit
startup/ramp constraints and initial conditions, and independent held-out
PMSS outcomes. This is a **simplified DC/UC research model**, not
PMSS AC flow, reserve cooptimization, full SCUC, SCED or settlement.
