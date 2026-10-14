"""healthlake_ingestion: one batch from landing to a published Gold release.

Triggered by healthlake_discovery (run_id batch__<batch_id>) or manually with conf {"batch_id": "<64 hex>"}.
Every task calls the HealthLake CLI; XCom carries only ids and counters.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import DAG, Param, TriggerRule, get_current_context, task

from _healthlake.cli import run_cli

INGEST_POOL = "healthlake_ingestion"
PUBLISH_POOL = "healthlake_publication"

default_args = {
    "owner": "healthlake",
    "retries": 2,
    "retry_delay": timedelta(seconds=30),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(minutes=30),
}

with DAG(
    dag_id="healthlake_ingestion",
    description="Synthetic healthcare batch: verify, archive, FHIR, quarantine, Silver, dbt Gold, publish.",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=2,
    default_args=default_args,
    params={"batch_id": Param(type="string", pattern="^[0-9a-f]{64}$", description="Registered batch id")},
    tags=["healthlake", "synthetic-data"],
    doc_md=__doc__,
) as dag:

    @task(pool=INGEST_POOL)
    def start_attempt() -> dict:
        ctx = get_current_context()
        batch_id = ctx["params"]["batch_id"]
        return run_cli("start", "--batch-id", batch_id, "--run-id", ctx["run_id"])

    @task(pool=INGEST_POOL)
    def verify(started: dict) -> dict:
        return run_cli("verify", "--batch-id", started["batch_id"])

    def step(name: str, cli_name: str, timeout_min: int = 30):
        @task(task_id=name, pool=INGEST_POOL, execution_timeout=timedelta(minutes=timeout_min))
        def _step(started: dict, _previous: dict | None = None) -> dict:
            return run_cli(
                cli_name,
                "--processing-id",
                started["processing_id"],
                "--attempt-id",
                started["attempt_id"],
                timeout=timeout_min * 60,
            )

        return _step

    @task(pool=PUBLISH_POOL)
    def build_snapshot(started: dict, _loaded: dict) -> dict:
        return run_cli("build-snapshot", "--processing-id", started["processing_id"])

    @task(pool=PUBLISH_POOL, execution_timeout=timedelta(minutes=60))
    def dbt_build(release: dict) -> dict:
        return run_cli("dbt-build", "--release-id", release["release_id"], timeout=3600)

    @task(pool=PUBLISH_POOL)
    def dbt_docs(release: dict, _built: dict) -> dict:
        return run_cli("dbt-docs", "--release-id", release["release_id"])

    @task(pool=PUBLISH_POOL)
    def quality_gate(release: dict, _docs: dict) -> dict:
        return run_cli("quality-gate", "--release-id", release["release_id"])

    @task(pool=PUBLISH_POOL)
    def publish(release: dict, _gate: dict) -> dict:
        return run_cli("publish", "--release-id", release["release_id"])

    @task(trigger_rule=TriggerRule.ALL_DONE, retries=1)
    def final_report() -> dict:
        """Always runs. Closes the attempt and writes the report, then FAILS unless the batch is loaded and its
        release is published: a successful report task must never turn a failed run green."""
        from airflow.sdk.exceptions import AirflowFailException

        ti = get_current_context()["ti"]
        started = ti.xcom_pull(task_ids="start_attempt")
        if not started or "attempt_id" not in started:
            raise AirflowFailException("no attempt was started; see start_attempt logs")
        run_cli("finish", "--attempt-id", started["attempt_id"])
        return run_cli("report", "--attempt-id", started["attempt_id"], "--fail-on-unsuccessful")

    started = start_attempt()
    verified = verify(started)
    archived = step("archive", "archive")(started, verified)
    adapted = step("adapt", "adapt")(started, archived)
    validated = step("validate", "validate", timeout_min=60)(started, adapted)
    resolved = step("resolve_references", "resolve")(started, validated)
    classified = step("classify_quality", "classify")(started, resolved)
    normalized = step("normalize", "normalize")(started, classified)
    loaded = step("load_silver", "load")(started, normalized)
    release = build_snapshot(started, loaded)
    built = dbt_build(release)
    docs = dbt_docs(release, built)
    gate = quality_gate(release, docs)
    published = publish(release, gate)
    published >> final_report()
