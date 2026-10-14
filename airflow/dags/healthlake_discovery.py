"""healthlake_discovery: every 5 minutes (UTC), register finalized batches and trigger one ingestion run per
pending batch. Run ids are deterministic (batch__<batch_id>), so a trigger missed by a crash is recreated on the
next run and an existing run is never duplicated."""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.sdk import DAG, task

from _healthlake.cli import run_cli

with DAG(
    dag_id="healthlake_discovery",
    description="Register finalized landing batches and trigger healthlake_ingestion.",
    schedule="*/5 * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(seconds=20),
        "retry_exponential_backoff": True,
        "execution_timeout": timedelta(minutes=10),
    },
    tags=["healthlake", "synthetic-data"],
    doc_md=__doc__,
) as dag:

    @task
    def discover() -> list[dict]:
        result = run_cli("discover")
        return [
            {"trigger_run_id": f"batch__{bid}", "conf": {"batch_id": bid}}
            for bid in result.get("pending_batch_ids", [])
        ]

    TriggerDagRunOperator.partial(
        task_id="trigger_ingestion",
        trigger_dag_id="healthlake_ingestion",
        skip_when_already_exists=True,
        wait_for_completion=False,
    ).expand_kwargs(discover())
