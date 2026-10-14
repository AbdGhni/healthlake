# HealthLake — implementation plan

HealthLake is a technical demonstration using synthetic data only.
It is not a certified healthcare platform and is not intended or
authorized to process real personal health data.

Phases follow the master prompt (section 20). Each phase ends with tests run and status updated.

0. Inspection and plan (this file).
1. Versions, lockfiles, SQL migrations (ctl, bronze, silver, quality).
2. Synthetic data generation (3 sources) and fixtures.
3. Batch manifests, registry, Bronze RawStore (SHA-256 content addressed).
4. Adapters to FHIR R4, validation, reference resolution.
5. Silver load (atomic per processing), CLI.
6. Deterministic snapshot, dbt in candidate schema, quality gate, atomic publication.
7. Airflow DAGs (discovery, ingestion), recovery.
8. Quality catalogue, quarantine, observability.
9. FastAPI (keyset pagination pinned to a release).
10. Streamlit dashboard (API only).
11. Dockerfiles, compose, CI, backup/restore.
12. E2E, crash tests, measured performance.
13. Documentation and portfolio material.
14. Final verification.

## Environment constraints found on 2026-10-14
- No Docker daemon reachable from the build sandbox (Docker Desktop is on the user's Windows host only).
  Image builds, compose startup and the clean-environment run are therefore unverified here.
- PostgreSQL 16.15 is the only server available in the sandbox; PG 17 is the target in compose.
  Integration tests, dbt, API and crash tests run on PG 16 locally. SQL must avoid PG17-only features.
- GitHub is partially filtered; Synthea download is attempted, with a project generator as fallback.
- Python 3.12.3 is available (target version).
