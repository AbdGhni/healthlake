# Implementation status

Last update: 2026-10-14, end of phase 5.

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

## Tests (all run, all pass): 56
- unit 21, integration 28 (migrations + section 19.1 data cases), recovery 5 (crash points 1-3, hard kill,
  concurrent attempts), fhir 1 (real HL7 validator), config/CLI 3.
- ruff, ruff format, mypy --strict: clean.

## Not verified
- PostgreSQL 17, Java 17, Docker images (no daemon in the sandbox).
- Extended profile (1 000 patients) not run yet (planned in phase 12).
