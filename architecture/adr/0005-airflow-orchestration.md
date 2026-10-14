# ADR 0005: Airflow 3 orchestration through the HealthLake CLI

Status: accepted (2026-10-14)

- Two DAGs. `healthlake_discovery` (cron `*/5 * * * *`, UTC, no catchup, one active run) calls
  `healthlake discover`, then triggers `healthlake_ingestion` once per pending batch with run id
  `batch__<batch_id>` and `skip_when_already_exists=True`. Pending = registered/verified/archived batches without a
  loaded or blocked processing for the current code version, so a trigger lost in a crash is recreated by the
  next discovery run and an existing run is never duplicated.
- `healthlake_ingestion` has 15 tasks, each a subprocess call to the CLI in its own virtualenv
  (`HEALTHLAKE_CLI`, default `/opt/healthlake-venv/bin/healthlake`). Airflow never imports HealthLake or dbt.
- Exit codes: 2/3/5 raise `AirflowFailException` (no retry: the data must change); 1/4 raise and are retried
  twice with exponential backoff. Every task has an execution timeout. Pools `healthlake_ingestion` (1) and
  `healthlake_publication` (1); `max_active_runs=1`; `max_active_tasks=2`.
- `final_report` (trigger rule `all_done`) is the only leaf. It closes the attempt, writes the report, and
  fails unless the attempt succeeded and its release is published. A green report can therefore not hide a
  failed processing (verified on a live Airflow 3.3.2 run).
- XCom carries only ids and counters (whitelist in `_healthlake/cli.py`). DAG files do no database or network
  access at import (tested by blocking sockets during DagBag parsing).
- Authentication: FAB auth manager (users in the Airflow metadata DB), admin password from a secret file.
