# Test report

> HealthLake is a technical demonstration using synthetic data only.
> It is not a certified healthcare platform and is not intended or
> authorized to process real personal health data.

Last full run: 2026-10-15, development sandbox. Python 3.12.3, PostgreSQL 16.15, dbt-core 1.12.6, Airflow 3.3.2,
no Docker daemon. Everything below was actually run; what was not run is listed at the end with the command to
run it.

## Automated suites
| Suite | Environment | Command | Result |
|---|---|---|---|
| App (unit, integration, recovery, FHIR, API) | `.venvs/app` | `pytest -q` | **81 passed**, 1 skipped (the dashboard module, which runs in its own environment) |
| Airflow DAGs | `.venvs/airflow` | `pytest -q tests/airflow` | **12 passed** (also with an empty `AIRFLOW_HOME`, as in CI) |
| Dashboard | `.venvs/dashboard` | `pytest -q tests/dashboard` | **10 passed** |
| dbt data tests | inside every release build | `healthlake dbt-build` | **100/100** on the test, demo and extended releases |
| Lint and types | `.venvs/app` | `ruff check .`, `ruff format --check .`, `mypy --strict src` | clean (150 files, 53 typed modules) |

Environment variables for the app suite: `HEALTHLAKE_TEST_ADMIN_DSN` (a PostgreSQL superuser DSN; every test
database is created and dropped), `HEALTHLAKE_DBT_BIN` (release tests) and `HEALTHLAKE_HL7_VALIDATOR_JAR` (one test
with the real HL7 validator).

### What the app suite covers
| Area | Tests |
|---|---|
| Section 19.1 data cases (`tests/integration/test_ingestion_cases.py`, 24) | three sources reconcile; identical replay; truncated JSON; invalid CSV header; one bad row under the threshold, quarantined; bad rows over the threshold, blocked; invalid manifest; altered file; undeclared file; same revision with different content; duplicate file stored once; duplicate resource; same id with different content; identity conflict; missing patient; patient/encounter mismatch; rejection cascade with cause; contained references, partial dates, absent values, components, out of scope; inverted period; absolute and external references; valid update, invalid update, backfill; CLI exit codes |
| Crash and concurrency (`tests/recovery`, 7; `tests/integration/test_release.py`, 8) | crash points 1-7, crash then rerun gives a single copy, `kill -9` after the Silver commit and after the publish commit, concurrent attempts on one batch, a second attempt refused while the first holds the lock, final report crash and blocked processing |
| Release (`test_release.py`) | publish, rebuild idempotence and switch; a failed gate keeps the previous release; a blocked processing does not change the active release; retention; non-blocking release observations |
| Database (`test_migrations.py`, 6) | idempotent init, checksum guard on applied migrations, API role cannot read Silver/Bronze, ingest role cannot create schemas, only the ingestion role can refresh snapshot statistics, singleton active release |
| Observability (`test_observability.py`, 6) | extreme values flagged not rejected, bounded metric labels, metrics when the database is down, password never printed, Bronze tamper detection, `gc-work` scope |
| API (`tests/api`, 2 scenario tests) | 401/403/404/410/422/503, release pinning, signed cursors, full pagination without duplicates, code filters (including an unknown code), summary equals Gold |
| Units and configuration (27) | canonical JSON, namespaced entity ids, release schema names, atomic and deterministic batch writer (from bytes and from files), symlink refusal, RawStore immutability, reference parsing, time precision, deterministic derivation, quality catalogue consistency, redaction, OpenAPI export up to date, secrets from files with no defaults |
| FHIR (1) | resources produced by the adapters pass the official HL7 validator 7.0.1 |

## End-to-end
| Run | How | Result |
|---|---|---|
| Five demo scenarios, **demo profile**, fresh database | `scripts/demo.py --scenario all --runner local --profile demo` | **all passed**: happy-path 390 s (328 patients, 12 206 encounters, 85 483 observations), quarantine 68 s (1 row quarantined and reported by `/v1/quality`), idempotent-replay 2 s (same release id), blocked-publication 47 s (batch blocked; gate failed; publication refused; active release unchanged), recovery 71 s (both attempts recorded, batch published) |
| Airflow 3.3.2 (api-server, scheduler, dag-processor, LocalExecutor) on PostgreSQL | phase 7, test profile | 3 successful runs, no duplicate triggers, failed-run semantics, no retry for data errors |
| Backup and restore | `scripts/backup.py` / `restore.py --runner local` | verified, see [restore-report.md](restore-report.md) |
| Dashboard in Chromium | `scripts/capture_screenshots.py` | 6 pages and the API docs captured on the demo profile ([screenshots](screenshots/README.md)) |
| Performance, demo and extended profiles | `scripts/perf_pipeline.py`, `scripts/perf_api.py` | see [performance/README.md](performance/README.md) |

## Defects found in phase 12 and fixed
Each fix has a test or a re-measurement.

| Found by | Defect | Fix |
|---|---|---|
| Extended generation | OOM kill at 5.7 GB: every Synthea bundle loaded and parsed at once | Streaming from disk; peak 1.45 GB; demo batches byte-identical; unit test bytes vs. files |
| Extended API load test | p95 about 1 s: no Gold indexes; `/v1/summary` counted the facts on every call | dbt index post-hooks plus `ANALYZE`; `agg_summary` with a reconciliation test; code filter on the indexed key; p95 under 80 ms |
| Extended pipeline | Snapshot 200 s: foreign-key checks row by row, nested loops on fresh rows | Migration 0008; hash joins in the snapshot transaction; 50 s |
| Demo scenarios, demo profile | Second release planned on stale statistics; two dbt models still running after 13 min | Migration 0009 `silver.analyze_snapshot()`; the whole quarantine scenario (ingestion and release) now takes 68 s; privilege test |
| Airflow suite without a metadata DB | `DagBag.get_dag()` queries the database in Airflow 3: the tests would have failed in CI | Tests read `dagbag.dags`; verified with an empty `AIRFLOW_HOME` |

Defects found in earlier phases are listed in [implementation-status.md](implementation-status.md).

## Not run here
| Item | Why | Command |
|---|---|---|
| Docker images, `docker compose up`, Airflow in containers, demo with the Docker runner | No Docker daemon in the sandbox | `make bootstrap build up demo` |
| PostgreSQL 17.11 | Sandbox has 16.15 | CI job `tests` (PostgreSQL 17 service), or the Compose stack |
| CI workflow on GitHub | Repository not pushed (needs your authorisation) | runs on the first push |
| Trivy image scan | Needs built images | CI job `e2e` |
| Extended profile through Airflow, extended warm pipeline | Time and disk budget of the sandbox | `docker compose run --rm synthea --profile extended --revision 1`, then the discovery DAG |
