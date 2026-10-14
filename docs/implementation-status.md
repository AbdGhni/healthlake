# Implementation status

Last update: 2026-10-14, end of phase 1.

## Phase 0, done
- Environment inspected, constraints recorded in docs/implementation-plan.md.

## Phase 1, done (verified in the sandbox)
- Lockfiles with hashes: requirements/{app,dbt,dashboard,dev}.lock. pip check OK (app, dbt, airflow venvs).
- Synthea 4.0.0 and HL7 validator 7.0.1 downloaded, SHA-256 pinned, CLI flags checked, offline validation run.
- SQL migrations 0001-0005: schemas ctl, bronze, silver, quality, api; tables from section 8; group roles; grants.
- Migration runner with checksums and advisory lock. `healthlake db-init` creates login users from secret files.
- CLI skeleton with JSON output and stable exit codes; `healthlake doctor`.
- Tests: 8 passed (pytest on PG16): idempotent init, edited migration rejected, API cannot read Silver/Bronze,
  ingest cannot create schemas, active_release singleton, secret handling, unreachable DB -> exit 4.
- ruff, ruff format, mypy --strict: clean.

## Not verified
- PostgreSQL 17, Java 17, Docker image digests (no daemon in the sandbox).

## Next: phases 2-3
Synthetic generation for 3 sources (Synthea + deterministic CSV/JSON derivation), manifests, registry, RawStore.
