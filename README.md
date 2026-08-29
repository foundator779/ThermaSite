# ThermaSite

**Size the facility. Find the five places built for it.**

ThermaSite is an agentic facility-siting estimator built for **FortyGuard Hackathon '26, Track 3 — Industrial & Enterprise**. A developer enters the planned campus acreage, IT design density, utilization, and cooling architecture. ThermaSite turns that into a planning load, pre-screens a versioned catalog of eight U.S. data-center markets, sends the five strongest candidates to FortyGuard with identical dates and same-scale AOIs, and returns an auditable ranked shortlist.

Each finalist appears on the map with a generated footprint matching the requested acreage, its FortyGuard heat layer, and heat-adjusted power and direct-water estimates. Judges can enter a shared persistent demo workspace with one click.

## Why it matters

Early data-center site selection is fragmented across temperature data, utility economics, water constraints, zoning, fiber, logistics, and local permitting. ThermaSite turns that research into one decision workflow:

1. The **Intake Agent** converts facility size and priorities into typed requirements and normalized weights.
2. The **Shortlist Agent** pre-screens eight cited U.S. markets and selects five for equal-footing analysis.
3. The **Heat Agent** submits a facility-sized GeoJSON AOI for each finalist to FortyGuard and polls the asynchronous status API.
4. The **Site Intelligence Agent** assembles sourced permitting, power, water, and infrastructure evidence.
5. The deterministic **Scoring Engine** ranks the five markets. Models cannot alter numerical scores.
6. The **Resource Estimator** combines FortyGuard heat metrics with explicit PUE and WUE assumptions to project facility power and selected-window water ranges.
7. The **Evidence Audit Gate** checks source coverage, thermal data, calculations, and uncertain claims.
8. The **Recommendation Agent** produces a decision summary, diligence queue, investment memo, and evidence bundle.

The UI exposes plans, tool calls, provider statuses, citations, and validation outcomes—not private model reasoning.

## Architecture

![ThermaSite production architecture](docs/architecture/thermasite-architecture.svg)

ThermaSite separates probabilistic research from deterministic decisions. Cloud Run serves the React workspace and FastAPI screening API. The coordinator runs typed agent stages, calls FortyGuard and grounded research providers through backend-only connectors, then hands stored facts to deterministic scoring, resource estimation, and an independent audit gate. Firestore preserves accounts and screening state; Cloud Storage holds downloadable evidence; Secret Manager injects provider credentials at runtime.

The editable source for the diagram is available in [Mermaid format](docs/architecture/thermasite-architecture.mmd).

## Facility-first input

The launch screen asks only for the information a developer already has:

- Campus footprint in acres
- IT design density in MW per acre
- Cooling architecture
- Expected utilization
- Optional investment priorities

Planned IT capacity is calculated as `acres × design density`. The default 40-acre, 1.25 MW/acre profile therefore represents 50 MW of planned IT capacity. This is a screening assumption, not a utility-capacity commitment or a parcel design.

## Decision and resource model

Default ranking weights are thermal/cooling 40%, power 25%, water 15%, permitting 10%, and logistics/infrastructure 10%. User values are normalized to 100%.

- Thermal suitability combines FortyGuard mean temperature, maximum temperature, and the 35°C exceedance ratio.
- Power uses a pinned, attributed EIA industrial-price snapshot plus sourced utility context.
- Water uses a clearly labeled WRI Aqueduct screening proxy plus local-provider diligence notes.
- Permitting follows a readiness rubric and never represents a permit guarantee.
- Infrastructure covers transport, fiber ecosystem, workforce, and documented industrial readiness.
- Missing FortyGuard evidence leaves a site visible but unranked.
- Missing secondary evidence receives a neutral score of 50 with zero confidence, lowering decision readiness.
- Hard-constraint failures stay visible but cannot become the recommended site.

Facility power uses a heat-adjusted PUE scenario. Direct water is shown as a cooling-system WUE range, never a single guaranteed value. Estimates cover the selected July window; annual extrapolation is disabled by default and does not affect ranking. FortyGuard supplies the ambient-heat evidence—the deterministic estimator translates that evidence into planning scenarios.

Each generated footprint is centered on an edge-of-market industrial search zone rather than a municipal centroid and matches the requested acreage. The close view uses satellite context so reviewers can see the surrounding land pattern. Aerial appearance does not establish vacancy or availability: the AOI is still an illustrative comparison, not a selected parcel, entitlement finding, utility-service boundary, or engineering layout.

## Local setup

Requirements: Python 3.11+, Node.js 22+, and Docker when using Compose.

```bash
cp .env.example .env
python -m pip install -e "backend[dev]"
cd frontend && npm install
```

Set these values in the root `.env`:

```dotenv
FORTYGUARD_API_KEY=your_backend_only_key
GOOGLE_API_KEY=your_gemini_key
GOOGLE_MAPS_API_KEY=your_optional_browser_maps_key
```

Never prefix the FortyGuard key with `VITE_`; it is read only by the backend and sent through the `api-key` header.

Run locally:

```bash
docker compose up --build
```

Or start each service:

```bash
python -m uvicorn terraforge.main:app --app-dir backend/src --reload --port 8000
cd frontend && npm run dev
```

Open `http://localhost:5173`. API documentation is at `http://localhost:8000/docs`.

## Accounts and persistence

- Registration stores an scrypt password hash—never the plaintext password.
- Revocable 30-day sessions survive browser refreshes and backend restarts.
- Local development persists users, sessions, and screenings under `.terraforge-data`.
- Production persists account and screening records in Firestore.
- Every screening, event stream, rescore operation, and artifact download is owner-scoped.
- **Enter judge demo** opens the shared `judge@thermasite.demo` workspace without exposing a password.
- The browser remembers the last active screening for each account; starting a new screen does not delete earlier decisions.

## Demo journey

1. Enter a 40-acre campus, 1.25 MW/acre design density, hybrid cooling, and 85% utilization.
2. Launch **Find my top five locations**.
3. Watch the trace show catalog pre-screening, five matched FortyGuard AOIs, cited research, scoring, resource estimation, and audit.
4. Select rank cards to move the map between five generated facility footprints and compare heat-adjusted power and water projections.
5. Review the leading candidate, factor scores, confidence, hard constraints, and next diligence actions.
6. Change power or water weight and apply an immediate persisted rescore without repeating provider calls.
7. Refresh to confirm the decision and facility estimates remain saved.
8. Open **Evidence & memo** to inspect citations and download the investment memo/evidence bundle.

## API

- `POST /api/v1/screenings` — create and queue a facility-first screening
- `GET /api/v1/screenings` — list prior screenings
- `GET /api/v1/screenings/{id}` — retrieve complete state and results
- `GET /api/v1/screenings/{id}/events` — stream agent/tool activity over SSE
- `POST /api/v1/screenings/{id}/rescore` — rescore stored facts without paid research
- `GET /api/v1/site-catalog` — retrieve the versioned eight-market catalog and source metadata
- `POST /api/v1/screenings/{id}/estimate` — optional compatibility endpoint for a custom follow-up AOI
- `POST /api/v1/auth/register` — create an account and session
- `POST /api/v1/auth/login` — authenticate an existing account
- `POST /api/v1/auth/demo` — enter the shared judge demo
- `GET /api/v1/auth/me` — restore the active account after refresh
- `POST /api/v1/auth/logout` — revoke the active session
- `GET /api/v1/readyz` — report provider, persistence, and artifact readiness without credentials

Legacy `/api/v1/runs` contracts remain as compatibility routes during the hackathon conversion, but the ThermaSite frontend does not call them.

## Verification

```bash
ruff check backend analysis_runtime
$env:PYTHONPATH='backend/src;.'; pytest -q backend/tests analysis_runtime/tests
cd frontend
npm run lint
npm test -- --run
npm run build
npm run test:e2e
```

Live smoke tests are opt-in because they consume provider calls.

## Deployment

The production web and API services run on Google Cloud Run in project `traceos-506713`. Firestore stores users and screenings, Cloud Storage stores artifacts, and Google Secret Manager injects FortyGuard, Gemini, and browser Maps credentials. Credentials are never returned in readiness output or activity logs.

## Sources and attribution

- Temperature analytics: [FortyGuard Temperature API](https://docs-api.fortyguard.com/)
- Industrial electricity snapshots: [U.S. Energy Information Administration](https://www.eia.gov/electricity/annual/table.php?t=epa_02_10.html)
- Water-risk framework: [WRI Aqueduct](https://www.wri.org/aqueduct), used under CC BY 4.0 with local verification required
- Permit and development evidence: official municipal planning/development sources listed per candidate

## Scope boundary

ThermaSite is a screening and due-diligence prioritization product. It does not discover or purchase parcels, file permits, guarantee utility capacity, determine water rights, perform cooling-system engineering, or replace legal, environmental, technical, or financial underwriting.
