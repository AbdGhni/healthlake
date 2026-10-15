# 5-minute demo script

Preparation (before the call): stack up, `happy-path` already run, browser tabs open on the dashboard
(Overview), the API docs, and Airflow. Terminal in the repository.

| Time | Show | Say |
|---|---|---|
| 0:00-0:30 | README top (disclaimer + architecture diagram) | "HealthLake is a local healthcare data platform on synthetic data only. Three fictional hospitals send FHIR, CSV and JSON; I turn that into a tested, published analytics model." |
| 0:30-1:15 | Airflow: `healthlake_ingestion` graph, one green run | "One run per batch. Each box is a CLI step with a strict exit-code contract: data errors fail fast, transient errors retry. The last task fails the run unless the release is really published." |
| 1:15-2:00 | Dashboard Overview, then Data Quality | "The dashboard only talks to the API. Every page is pinned to one release id. Here, reconciliation: every received resource has exactly one outcome." |
| 2:00-3:00 | Terminal: `python scripts/demo.py --scenario quarantine` | "A new batch with one corrupted value among 120 new observations. That row goes to quarantine, the rest is published, and the API reports the issue." Switch to Data Quality: the quarantined row is visible. |
| 3:00-4:00 | Terminal: `python scripts/demo.py --scenario blocked-publication` | "Now a batch with a broken CSV header, then a release whose dbt tests fail. Both are refused, and the active release id does not change: publication is an atomic pointer switch after a gate." |
| 4:00-4:40 | API docs: `/v1/observations` with a cursor | "Read-only API: hashed keys with scopes, and keyset pagination with signed cursors pinned to a release, so paging stays consistent while new releases are published." |
| 4:40-5:00 | docs/known-limits.md | "And what I don't claim: not a medical product, single node, and the Docker stack still has to be verified on a Docker host." |

Fallback when the live stack is not available: use the screenshots in `docs/screenshots/` and the
recorded scenario output from the local runner (`python scripts/demo.py --runner local --scenario all`).
