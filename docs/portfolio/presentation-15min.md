# 15-minute presentation plan

Audience: a data engineering interview panel or a meetup. Ten slides, with a live demo in the middle (fallback:
screenshots). Each line below is one slide.

| # | Minutes | Slide | Content | Evidence to show |
|---|---|---|---|---|
| 1 | 0:00-0:45 | Title | HealthLake: a tested, local healthcare analytics platform on synthetic data. The disclaimer, read aloud. | README header |
| 2 | 0:45-2:00 | Problem | Three hospitals, three formats (FHIR, CSV, JSON), late and duplicated deliveries, bad rows. Analysts need one consistent model and must never see a half-built release. | Data contract |
| 3 | 2:00-3:30 | Architecture | Landing, Bronze (SHA-256 RawStore), FHIR R4, Silver (historised), snapshot, Gold candidate schema, gate, atomic publication, API, dashboard. Airflow around it. | README diagram |
| 4 | 3:30-5:00 | Correctness by construction | Deterministic ids (batch, processing, entity, release). Four disjoint outcomes plus reconciliation. Processing gate rules. | architecture.md diagrams 2 and 6 |
| 5 | 5:00-6:15 | Failure handling | Exit-code contract, retries only for transient errors, advisory lock, idempotent steps, crash points 1-7, final_report as the only leaf. | architecture.md diagram 4, tests/recovery |
| 6 | 6:15-9:15 | Live demo | Scenarios `quarantine` and `blocked-publication`, then the dashboard's Data Quality page and the API with a cursor. | demo-script-5min.md |
| 7 | 9:15-10:30 | Release and serving | dbt with 100 tests in a candidate schema; a release gate; API keys stored as hashes; signed cursors pinned to a release; the dashboard talks to the API only. | docs/api/README.md |
| 8 | 10:30-12:00 | Measured, not guessed | Pipeline time per step, peak memory, dbt time, API p50/p95 with 5 clients, cold vs warm, 100 vs 1 000 patients. Where the time goes and what to do about it. | docs/performance/README.md |
| 9 | 12:00-13:15 | What testing found | Bugs found by tests and fixed (cross-source merge, rollback losing quarantine, time zones, backup secrets) and by the 1 000-patient run (OOM in generation, missing Gold indexes, slow snapshot). What is not verified yet. | implementation-status.md, known-limits.md |
| 10 | 13:15-15:00 | Lessons and next steps | Trade-offs (sampled HL7 validation, no MPI, single node). Backlog: parallel validation, incremental dbt, Docker-host verification. Questions. | extension-backlog.md |

Speaker notes:
- Keep every number traceable to a file in `docs/performance/` or a test. If someone asks about something not
  measured, say so.
- Do not call it production-ready or compliant. The point is the engineering discipline, not a product.
