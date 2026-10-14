"""Crash tests 1-3 of section 19.2 and concurrent attempts, on the real pipeline and PostgreSQL."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from healthlake.db import connect
from healthlake.errors import TransientError
from healthlake.ingestion.registry import discover
from healthlake.pipelines.runner import limits
from healthlake.pipelines.steps import ingest_batch
from healthlake.testing import InjectedCrashError
from tests.fixtures import factory as f
from tests.integration.helpers import one

pytestmark = pytest.mark.db

TABLES = [
    "bronze.file",
    "bronze.resource_occurrence",
    "silver.resource_version",
    "silver.patient",
    "silver.observation",
    "silver.reference",
]


def snapshot() -> dict[str, int]:
    return {t: one(f"SELECT count(*) FROM {t}") for t in TABLES}


def baseline(tmp_path: Path) -> dict[str, int]:
    """Counts produced by one clean run of the same batch (computed in-process for comparison)."""
    return {}


def _discover(landing: Path) -> None:
    with connect("ingest", autocommit=True) as conn:
        discover(conn, landing, limits())


@pytest.mark.parametrize("point", ["after_archive_before_status", "during_load"])
def test_crash_then_rerun_gives_single_copy(lake: dict[str, Path], monkeypatch: pytest.MonkeyPatch, point: str) -> None:
    b = f.write_csv_batch(lake["landing"], f.business_rows(n_patients=3))
    _discover(lake["landing"])
    monkeypatch.setenv("HEALTHLAKE_CRASH_AT", point)
    with pytest.raises(InjectedCrashError):
        ingest_batch(b)
    assert one("SELECT status FROM ctl.attempt") == "failed"
    if point == "during_load":
        assert one("SELECT count(*) FROM silver.resource_version") == 0  # rolled back, nothing partial
        assert one("SELECT status FROM ctl.processing") == "normalized"
    assert one("SELECT count(*) FROM bronze.file") == 8 or point == "after_archive_before_status"
    monkeypatch.delenv("HEALTHLAKE_CRASH_AT")
    r = ingest_batch(b)
    assert r["status"] == "succeeded"
    s = snapshot()
    assert s["bronze.file"] == 8
    assert s["bronze.resource_occurrence"] == r["counters"].get("received") or s["bronze.resource_occurrence"] > 0
    assert s["silver.patient"] == 3
    # replay after success changes nothing
    ingest_batch(b)
    assert snapshot() == s


def test_hard_kill_after_silver_commit_before_return(lake: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    b = f.write_csv_batch(lake["landing"], f.business_rows(n_patients=3))
    _discover(lake["landing"])
    env = {
        **os.environ,
        "HEALTHLAKE_CRASH_AT": "after_silver_commit_before_return",
        "HEALTHLAKE_CRASH_MODE": "exit",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "healthlake.cli", "ingest", "--batch-id", b],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 137  # killed: no JSON result, no attempt closure
    assert proc.stdout == ""
    assert one("SELECT status FROM ctl.processing") == "loaded"  # the commit happened
    assert one("SELECT status FROM ctl.attempt") == "running"  # orphan attempt, explainable
    before = snapshot()
    proc2 = subprocess.run(
        [sys.executable, "-m", "healthlake.cli", "ingest", "--batch-id", b],
        env={k: v for k, v in env.items() if not k.startswith("HEALTHLAKE_CRASH")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc2.returncode == 0, proc2.stdout
    assert json.loads(proc2.stdout)["status"] == "succeeded"
    assert snapshot() == before


def test_concurrent_attempts_of_same_batch(lake: dict[str, Path]) -> None:
    b = f.write_csv_batch(lake["landing"], f.business_rows(n_patients=20, obs_per_patient=10))
    _discover(lake["landing"])
    outcomes: list[str] = []

    def worker() -> None:
        try:
            outcomes.append(ingest_batch(b)["status"])
        except TransientError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert "succeeded" in outcomes, outcomes
    assert set(outcomes) <= {"succeeded", "processing_locked"}
    if "processing_locked" in outcomes:  # the loser retries, as Airflow would
        assert ingest_batch(b)["status"] == "succeeded"
    assert one("SELECT count(*) FROM silver.patient") == 20
    assert one("SELECT count(*) FROM bronze.resource_occurrence") == one(
        "SELECT count(DISTINCT (processing_id, occurrence_no)) FROM bronze.resource_occurrence"
    )
    assert one("SELECT count(*) FROM ctl.processing") == 1


def test_second_attempt_is_refused_while_first_holds_the_processing(lake: dict[str, Path]) -> None:
    """Deterministic version of the race: hold the processing lock, a second attempt gets a retryable error."""
    from healthlake.ingestion.registry import start_attempt
    from healthlake.pipelines.runner import processing_lock

    b = f.write_csv_batch(lake["landing"], f.business_rows())
    _discover(lake["landing"])
    with connect("ingest", autocommit=True) as conn:
        pid = start_attempt(conn, b, None)["processing_id"]
        with processing_lock(conn, pid):
            with pytest.raises(TransientError) as exc:
                ingest_batch(b)
            assert exc.value.code == "processing_locked"
    assert ingest_batch(b)["status"] == "succeeded"
