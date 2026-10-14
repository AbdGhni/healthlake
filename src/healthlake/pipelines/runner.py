"""Step dispatch shared by the CLI and tests. Each processing step holds a PostgreSQL advisory lock
on its processing id, so two concurrent attempts of the same batch serialize instead of racing."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import Any

import psycopg

from healthlake.config import paths
from healthlake.db import connect
from healthlake.errors import TransientError
from healthlake.generation.synthea import load_json
from healthlake.ingestion.manifest import Limits
from healthlake.ingestion.rawstore import LocalRawStore
from healthlake.observability import set_context
from healthlake.pipelines.workspace import Workspace


@cache
def sources_config() -> dict[str, Any]:
    return load_json("sources.json")


def limits() -> Limits:
    return Limits()


def store() -> LocalRawStore:
    return LocalRawStore(paths().lake / "bronze")


def workspace(pid: str) -> Workspace:
    return Workspace(paths().work, pid)


@contextmanager
def processing_lock(conn: psycopg.Connection, pid: str) -> Any:
    key = int(pid[:15], 16)
    got = conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()
    if not got or not got[0]:
        raise TransientError("another attempt holds this processing", code="processing_locked")
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (key,))


def run_processing_step(
    pid: str,
    step: Callable[[psycopg.Connection, Workspace], dict[str, Any]],
    attempt_id: str | None = None,
    step_name: str | None = None,
) -> dict[str, Any]:
    set_context(processing_id=pid, attempt_id=attempt_id)
    with connect("ingest", autocommit=True) as conn:
        with processing_lock(conn, pid):
            if attempt_id and step_name:
                conn.execute("UPDATE ctl.attempt SET current_step=%s WHERE attempt_id=%s", (step_name, attempt_id))
            # autocommit connection: each step commits its own explicit transactions, so state written
            # before a blocking decision (quarantine, blocked status) survives the raised error.
            result = step(conn, workspace(pid))
    return result


def dumps(o: Any) -> str:
    return json.dumps(o, sort_keys=True)


def landing() -> Path:
    return paths().landing
