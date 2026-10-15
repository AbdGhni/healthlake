# Implementation status

Last update: 2026-10-14, end of phase 11.

## Phases 0-1 (done, verified)
Plan, locked dependencies, Synthea 4.0.0 and HL7 validator 7.0.1 pinned, migrations, roles, CLI skeleton.

## Phase 2: generation (done, verified)
- `healthlake generate --profile test|demo|extended` runs pinned Synthea three times (seeds 1001/1002/1003,
  clinician seeds 2001/2002/2003, reference/end date 2026-01-01, UTC, 1 thread, 5 years of history) and writes
  three finalized batches: FHIR bundles (horizon-central), CSV (horizon-nord), JSON (horizon-sud).
- Measured: demo profile = 110 / 110 / 108 patients exported (Synthea adds deceased patients to the requested 100);
  generation 168 s wall, 1.36 GB peak RSS; batches 241 MB / 9.8 MB / 21 MB.
- Test fixtures without Java: `tests/fixtures/factory.py`.

## Phase 3: manifests, registry, Bronze (done, verified)
- Manifest contract (pydantic), discovery of finalized directories, registration, verification (sizes, hashes,
  undeclared/missing files, symlinks), revision conflicts.
- LocalRawStore: content-addressed, exclusive creation via os.link, read verification, reconciliation.

## Phase 4: adapters, validation, references (done, verified)
- Adapters: FHIR bundles, horizon-csv-v1, horizon-json-v1 -> FHIR R4 resources with locators (JSON pointer or line).
- Structural validation `val-1` on every resource; HL7 validator audit on a sample (ADR 0003): 0 unexplained
  errors on the three demo sources.
- Reference resolution: urn:uuid/fullUrl, relative, absolute with declared base, contained, identifier
  (conditional and logical). External references refused, never fetched.
- Patient/encounter consistency, dependency propagation with cause, duplicates, content conflicts,
  identity conflicts, invalid updates.

## Phase 5: Silver (done, verified)
- classify: quarantine persisted in `quality.issue` (with `caused_by_issue_id`), check results, gate
  (fatal issues, conflicts, invalid updates, reject rate of new resources <= 1 %, reconciliation).
- normalize + load: one transaction per processing, COPY into staging, post-load checks, status `loaded`.
- Demo profile pipeline (Bronze to Silver, HL7 audit included), sandbox: central 113 s (87 326 resources),
  nord 43 s (32 278), sud 54 s (40 507). Peak RSS 1.8 GB (includes the Java validator).

## Phase 6: snapshot, dbt, gate, publication (done, verified)
- dbt project (dbt-core 1.12.6, dbt-postgres 1.11.0): 9 staging views, 2 intermediate views, 5 dimensions,
  6 facts (incl. bridge), 4 aggregates, 2 seeds, 1 analysis, 91 data tests (generic + 7 singular).
- Commands `build-release`, `quality-gate`, `publish`; retention and purge. ADR 0004.
- Demo profile (328 patients, 160 111 snapshot members): build 26 s, gate 0.3 s, publish 0.2 s; 91/91 dbt tests pass.
  Gold rows: 12 206 encounters, 85 483 observations, 38 355 components, 7 493 conditions, 8 670 prescriptions.
- dbt tests caught two real bugs during development (ambiguous column in dim_code; dim_date bounds computed
  in the session time zone instead of UTC), both fixed.

## Phase 7: Airflow and recovery (done, verified)
- DAGs `healthlake_discovery` and `healthlake_ingestion` (ADR 0005), helper `_healthlake/cli.py`.
- New CLI commands: `build-snapshot`, `dbt-build`, `dbt-docs`, `report`, `backfill` (release build split into tasks).
- Live verification in the sandbox (no Docker): Airflow 3.3.2 api-server + scheduler + dag-processor with
  LocalExecutor on a PostgreSQL metadata DB, FAB authentication (unauthenticated API call -> 401):
  - discovery triggered 3 ingestion runs (test profile), all `success` (2m18s, 1m01s, 1m02s), 3 releases
    published in turn, the last one active;
  - re-running discovery 4 more times created no new ingestion run;
  - an invalid CSV batch: `classify_quality` failed on try 1 (no retry), downstream `upstream_failed`,
    `final_report` ran and failed on try 1, run `failed`, active release unchanged.
- Crash point 7 (during final report) and final-report semantics covered by tests.

## Phase 8: quality and observability (done, verified)
- Versioned catalogue `config/quality-catalog.json` (qc-1, 40 checks) rendered to docs/quality-catalog.md; a test
  fails if code emits a check id missing from the catalogue or if the doc is stale.
- New checks: extreme values (`value.extreme`, warnings, `config/plausibility.json`), release observations
  (terminology coverage, clinical-data freshness, completeness), `verify-bronze` reconciliation.
- Prometheus collector with bounded labels (`healthlake metrics`; API `/metrics` in phase 9), command duration
  logs, secret redaction, `gc-work`.
- Runbooks for the 7 pipeline situations (docs/runbooks). API, dashboard and restore runbooks come with phases 9-11.
- Bug found and fixed: replaying a batch after its work files were cleaned re-ran adaptation and temporarily
  moved the processing status back; steps now decide idempotence from the database first (tested).

## Phase 9: API (done, verified)
- FastAPI app `healthlake.api.app` (13 paths, OpenAPI exported to docs/api/openapi.json, contract in docs/api/README.md).
- X-API-Key with hashed storage and constant-time comparison, scopes `read`/`ops`; `healthlake api-keys`.
- Keyset pagination with HMAC-signed cursors pinning release, endpoint and filters; default 50, max 200.
- 401/403/404/410/422/503 behaviours tested; read-only DB sessions with statement timeout; `/metrics` with API
  latency histogram and request counter by route template.
- Live check under uvicorn (2 workers) on the published test profile: readiness 200, no key 401, summary
  10 patients / 236 encounters / 1 447 observations, `/docs` 200.

## Phase 10: dashboard (done, verified)
- Streamlit 1.65 app, 6 pages through the API only (docs/dashboard.md), release pinned per page run, cache keyed
  by release id, indicator definitions, empty/error states, accessible palette with fixed colour per entity.
- Verified live: uvicorn API + Streamlit + Chromium (Playwright); screenshots in docs/screenshots (test profile).
- Visual review found and fixed: hidden bar labels, header wrapping, raw `None`/fractions in the quality table,
  and an API defect: timestamps were returned in the server time zone (+02:00); API sessions now use UTC.

## Phase 11: Docker, CI, bootstrap, backup/restore (written; partly verified)
- 3 Dockerfiles (platform, api, dashboard), docker-compose.yml (10 services incl. tools profile, 2 networks,
  6 volumes, 14 file secrets, healthchecks, loopback ports), Postgres init for the Airflow DB, airflow-init.
- `docker compose config` validates; images pinned by digest, Temurin JRE and jars by SHA-256 (docs/deployment.md).
- `scripts/bootstrap.py` (prerequisites, secrets never printed, --rotate-api-keys), `scripts/wait_ready.py`,
  `scripts/demo.py` (5 scenarios with assertions, docker or local runner), Makefile.
- `healthlake scenario-batch` builds the quarantine/extend/invalid demo batches from the original nord batch.
- Demo scenarios verified with the local runner on a fresh database: happy-path, quarantine, idempotent-replay,
  blocked-publication, recovery all pass.
- Backup/restore verified with the local runner (docs/restore-report.md): hashes, Bronze re-hash, reconciliation,
  API smoke test, refusal of a corrupted backup and of a non-empty target. Roles dumped without passwords.
- CI workflow: lint/type/catalogue, pip-audit per lockfile, gitleaks, tests on PostgreSQL 17 service, Airflow,
  dashboard, e2e with compose + demo + backup/restore + Trivy; actions pinned by SHA, `contents: read`.
  Run locally: pip-audit (no known vulnerability in app, dbt, dashboard locks), gitleaks on git history (no leak).
- Bugs found while writing scenarios and fixed: a scenario derived from a blocked batch; adapter-rejected rows
  produced 3 extra validation issues on their stub resource.
- Not verified: image builds, compose up, Airflow in containers, PostgreSQL 17, the docker runner of demo/backup.

## Phase 12: end-to-end, extended profile, performance (done, verified without Docker)
- Five demo scenarios pass on the **demo profile** on a fresh database (local runner); screenshots recaptured
  from that state.
- Performance measured with a reproducible protocol (fresh database per run; cold = PostgreSQL restart + page
  cache dropped): generation, per-step pipeline time, peak memory, database and directory sizes, API latency
  with 5 clients, cold and warm, demo and extended (1 000 patients per source) profiles. JSON results and the
  analysis are in docs/performance.
- Extended pipeline: 1.79 M resources in 1 841 s; API p95 under 80 ms on 1 M observations.
- Defects found and fixed (each re-measured or tested):
  - OOM in generation (now streamed from disk);
  - missing Gold indexes and live summary counts (dbt index hooks, `agg_summary`, code-key filter);
  - slow snapshot (migration 0008);
  - stale statistics before dbt (migration 0009);
  - DAG tests that needed an Airflow metadata database.
- Test report: docs/test-report.md.

## Phase 13: documentation and portfolio (drafted during phase 12)
- English README; docs/architecture.md (6 diagrams and the ERD); generated docs/data-dictionary.md;
  docs/known-limits.md; docs/portfolio (5-minute demo, 15-minute talk, CV and LinkedIn texts in English and
  French, interview Q&A, extension backlog).

## Tests (all run, all pass): 81 (app venv) + 12 (Airflow venv) + 10 (dashboard venv); 100 dbt data tests
- Airflow venv: 12 DAG tests (import without network/DB, task contract, single leaf, retries, pools, params,
  exit-code mapping, deterministic run ids).
- App venv by file: unit/config 27, integration 44 (ingestion cases 24, migrations 6, observability 6, release 8
  with real dbt builds), recovery 7, API 2 scenario tests, FHIR 1 (real HL7 validator). Details: docs/test-report.md.
- ruff, ruff format, mypy --strict: clean.

## Not verified
- PostgreSQL 17, Java 17, Docker images (no daemon in the sandbox).
