
# PMSS Unified Workspace frontend integration contract

The React workspace prefers server-authorized read-only PMSS data, falling back to the existing manual sanitized JSON import. These three paths are **proposed window A API contracts**, not live endpoints on main:

- GET /api/pmss/read-only/projects -> {"projects":[{"project_id":"opaque","name":"工程"}]}
- GET /api/pmss/read-only/cases?project_id=... -> {"cases":[{"case_date":"YYYY-MM-DD","label":"可选"}]}
- GET /api/pmss/read-only/snapshot?project_id=...&case_date=... -> {"source_kind":"authorized_pmss_read_only","read_only":true,"project_id":"opaque","case_date":"YYYY-MM-DD","snapshot":{...}}

Window A must validate session and per-project access, reject ambiguous same-day cases, provide only server-sanitized allowlisted snapshots, strip credentials, and disable public caching. Snapshot data must remain compatible with existing POST /api/pmss/inspect (unitTree/unitBids/marketSystem/24-hour demandForecastMw/forecastSource/caseDate and optional results/dcNetwork). No browser calls to teacher PMSS or VPN. Do not expose teacher credentials, URLs, raw private records, or a write endpoint.

The React UI validates source-kind/read-only flag/echoed project and date, data shape and size, then re-inspects data through existing API and reuses existing local strategy algorithms. The network diagram is a **topology schematic, not geographic geometry**; displayed bus loads and historical offer segments come solely from validated snapshot fields. Original historical clearing and local counterfactual simulation must never be confused.

Acceptance before production: backend API implemented and secured by window A, authorization denial/expired session tested, multiple projects/dates tested, 39/46/10 real model consistency checked privately, 24-hour historical data consistency verified, PR React build and regression tests green. Without backend adapter the UI reports unavailable and only supports existing manual imports. Do not claim PMSS live submissions or PMSS SCUC/SCED replication.

No changes to LiquidGlassCursor or existing Smirel global styling. No automatic merging or deployment.
