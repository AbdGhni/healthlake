"""DAG integrity, contracts and CLI exit-code mapping (run with the Airflow venv)."""

from __future__ import annotations

import itertools
import os
import socket
import stat
from pathlib import Path

import pytest

EXPECTED_TASKS = {
    "start_attempt",
    "verify",
    "archive",
    "adapt",
    "validate",
    "resolve_references",
    "classify_quality",
    "normalize",
    "load_silver",
    "build_snapshot",
    "dbt_build",
    "dbt_docs",
    "quality_gate",
    "publish",
    "final_report",
}


def test_no_import_errors(dagbag) -> None:  # type: ignore[no-untyped-def]
    assert dagbag.import_errors == {}
    assert {"healthlake_discovery", "healthlake_ingestion"} <= set(dagbag.dag_ids)


def test_import_does_not_touch_network_or_database(monkeypatch: pytest.MonkeyPatch) -> None:
    from airflow.models.dagbag import DagBag

    from tests.airflow.conftest import DAGS

    def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("network/database access during DAG import")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    bag = DagBag(dag_folder=str(DAGS))
    assert bag.import_errors == {}


def test_ingestion_dag_contract(dagbag) -> None:  # type: ignore[no-untyped-def]
    from airflow.sdk import TriggerRule

    dag = dagbag.dags["healthlake_ingestion"]
    assert {t.task_id for t in dag.tasks} == EXPECTED_TASKS
    assert dag.max_active_runs == 1
    assert dag.schedule is None
    assert "batch_id" in dag.params
    final = dag.get_task("final_report")
    assert final.trigger_rule == TriggerRule.ALL_DONE
    assert final.downstream_task_ids == set()  # the only leaf: its state decides the run state
    leaves = [t.task_id for t in dag.tasks if not t.downstream_task_ids]
    assert leaves == ["final_report"]
    for t in dag.tasks:
        if t.task_id != "final_report":
            assert t.retries == 2 and t.retry_exponential_backoff, t.task_id
            assert t.execution_timeout is not None, t.task_id
    assert dag.get_task("load_silver").pool == "healthlake_ingestion"
    assert dag.get_task("publish").pool == "healthlake_publication"
    # linear chain: verify -> ... -> publish
    order = [
        "start_attempt",
        "verify",
        "archive",
        "adapt",
        "validate",
        "resolve_references",
        "classify_quality",
        "normalize",
        "load_silver",
        "build_snapshot",
        "dbt_build",
        "dbt_docs",
        "quality_gate",
        "publish",
    ]
    for a, b in itertools.pairwise(order):
        assert b in dag.get_task(a).downstream_task_ids, (a, b)


def test_batch_id_param_is_validated(dagbag) -> None:  # type: ignore[no-untyped-def]
    from airflow.sdk import Param

    dag = dagbag.dags["healthlake_ingestion"]
    p: Param = dag.params.get_param("batch_id")
    p.resolve("a" * 64)
    with pytest.raises(Exception):  # noqa: B017 - airflow raises ParamValidationError
        Param(type="string", pattern="^[0-9a-f]{64}$").resolve("../../etc/passwd")


def test_discovery_dag_contract(dagbag) -> None:  # type: ignore[no-untyped-def]
    dag = dagbag.dags["healthlake_discovery"]
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.schedule == "*/5 * * * *"
    assert str(getattr(dag.timetable, "_timezone", "UTC")) in ("UTC", "Timezone('UTC')")
    trig = dag.get_task("trigger_ingestion")
    assert trig.partial_kwargs.get("skip_when_already_exists") is True


def _fake_cli(tmp_path: Path, code: int) -> str:
    p = tmp_path / f"fake_{code}.sh"
    p.write_text(
        f'#!/bin/sh\necho \'{{"ok": {"true" if code == 0 else "false"}, "processing_id": "x", '
        f'"secret_field": "dropped", "error_code": "e{code}"}}\'\nexit {code}\n'
    )
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


@pytest.mark.parametrize(
    "code,expected", [(0, None), (2, "fail"), (3, "fail"), (5, "fail"), (4, "retry"), (1, "retry")]
)
def test_run_cli_exit_code_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, expected: str | None
) -> None:
    from airflow.sdk.exceptions import AirflowFailException

    from _healthlake.cli import run_cli

    monkeypatch.setenv("HEALTHLAKE_CLI", _fake_cli(tmp_path, code))
    if expected is None:
        out = run_cli("discover")
        assert out == {"processing_id": "x"}  # only whitelisted ids/counters reach XCom
    elif expected == "fail":
        with pytest.raises(AirflowFailException):
            run_cli("classify")
    else:
        with pytest.raises(RuntimeError):
            run_cli("load")


def test_discover_builds_deterministic_run_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "disc.sh"
    p.write_text('#!/bin/sh\necho \'{"ok": true, "pending_batch_ids": ["' + "b" * 64 + "\"]}'\n")
    p.chmod(0o755)
    monkeypatch.setenv("HEALTHLAKE_CLI", str(p))
    from _healthlake.cli import run_cli

    pending = run_cli("discover")["pending_batch_ids"]
    runs = [{"trigger_run_id": f"batch__{b}", "conf": {"batch_id": b}} for b in pending]
    assert runs == [{"trigger_run_id": "batch__" + "b" * 64, "conf": {"batch_id": "b" * 64}}]
    assert os.environ["HEALTHLAKE_CLI"] == str(p)
