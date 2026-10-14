# Implementation status

Last update: 2026-10-14, end of phase 8.

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

## Tests (all run, all pass): 76 (app venv) + 12 (Airflow venv)
- Airflow venv: 12 DAG tests (import without network/DB, task contract, single leaf, retries, pools, params,
  exit-code mapping, deterministic run ids).
- unit 21, integration 35 (incl. 7 release tests with real dbt builds: happy path, rebuild idempotence, switch,
  failed gate keeps the active release, blocked processing, crash points 4-6, retention), earlier integration 28 (migrations + section 19.1 data cases), recovery 5 (crash points 1-3, hard kill,
  concurrent attempts), fhir 1 (real HL7 validator), config/CLI 3.
- ruff, ruff format, mypy --strict: clean.

## Not verified
- PostgreSQL 17, Java 17, Docker images (no daemon in the sandbox).
- Extended profile (1 000 patients) not run yet (planned in phase 12).
