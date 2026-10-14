"""Processing steps registry, attempt lifecycle and the local `ingest` convenience."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

import psycopg

from healthlake.db import connect
from healthlake.errors import ContractError, HealthLakeError
from healthlake.ingestion.registry import archive, processing_row, start_attempt, verify_batch
from healthlake.normalization.project import normalize
from healthlake.observability import log_event
from healthlake.pipelines.adapt_validate import adapt, validate
from healthlake.pipelines.load import load
from healthlake.pipelines.resolve import resolve
from healthlake.pipelines.runner import landing, limits, run_processing_step, sources_config, store
from healthlake.pipelines.workspace import Workspace
from healthlake.quality.processing_gate import classify

Step = Callable[[psycopg.Connection, str, Workspace, "str | None"], dict[str, Any]]

STEPS: dict[str, Step] = {
    "archive": lambda c, pid, ws, aid: archive(c, pid, landing(), store()),
    "adapt": lambda c, pid, ws, aid: adapt(c, pid, store(), ws, limits()),
    "validate": lambda c, pid, ws, aid: validate(c, pid, ws, store()),
    "resolve": lambda c, pid, ws, aid: resolve(c, pid, ws, sources_config()),
    "classify": lambda c, pid, ws, aid: classify(c, pid, aid, ws),
    "normalize": lambda c, pid, ws, aid: normalize(c, pid, ws),
    "load": lambda c, pid, ws, aid: load(c, pid, ws),
}
ORDER = ["archive", "adapt", "validate", "resolve", "classify", "normalize", "load"]


def _call(fn: Step, pid: str, aid: str | None, conn: psycopg.Connection, ws: Workspace) -> dict[str, Any]:
    return fn(conn, pid, ws, aid)


def finish_attempt(attempt_id: str, error: HealthLakeError | None = None) -> dict[str, Any]:
    """Close an attempt from the processing status. Never reports success for a failed processing."""
    with connect("ingest", autocommit=True) as conn:
        row = conn.execute(
            "SELECT a.processing_id, a.status, p.status, p.status_reason FROM ctl.attempt a"
            " JOIN ctl.processing p USING (processing_id) WHERE a.attempt_id=%s",
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise ContractError("unknown attempt", code="unknown_attempt")
        pid, a_status, p_status, reason = row
        if a_status != "running":
            return {"attempt_id": attempt_id, "status": a_status, "idempotent": True}
        if p_status == "loaded":
            status, code = "succeeded", None
        elif p_status == "blocked":
            status, code = "blocked", "processing_blocked"
        else:
            status, code = "failed", (error.code if error else "incomplete")
        conn.execute(
            "UPDATE ctl.attempt SET status=%s, error_code=%s, error_message=%s, finished_at=now() WHERE attempt_id=%s",
            (status, code, (str(error)[:1000] if error else reason), attempt_id),
        )
        log_event(
            "attempt_finished",
            conn=conn,
            processing_id=pid,
            attempt_id=attempt_id,
            level="info" if status == "succeeded" else "error",
            payload={"status": status},
        )
    return {"attempt_id": attempt_id, "processing_id": pid, "status": status, "processing_status": p_status}


def inspect_attempt(attempt_id: str) -> dict[str, Any]:
    with connect("ingest") as conn:
        a = conn.execute(
            "SELECT processing_id, status, current_step, error_code, started_at, finished_at FROM ctl.attempt"
            " WHERE attempt_id=%s",
            (attempt_id,),
        ).fetchone()
        if a is None:
            raise ContractError("unknown attempt", code="unknown_attempt")
        p = processing_row(conn, a[0])
        issues = conn.execute(
            "SELECT check_id, severity, cause_code, count(*) FROM quality.issue WHERE processing_id=%s"
            " GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 20",
            (a[0],),
        ).fetchall()
    return {
        "attempt": {
            "attempt_id": attempt_id,
            "status": a[1],
            "current_step": a[2],
            "error_code": a[3],
            "started_at": a[4],
            "finished_at": a[5],
        },
        "processing": {
            k: p[k] for k in ("processing_id", "batch_id", "status", "source_id", "source_revision", "counters")
        },
        "issues": [{"check_id": i[0], "severity": i[1], "cause_code": i[2], "count": i[3]} for i in issues],
    }


def ingest_batch(batch_id: str, run_id: str | None = None) -> dict[str, Any]:
    with connect("ingest", autocommit=True) as conn:
        verify_batch(conn, batch_id, landing())
        started = start_attempt(conn, batch_id, run_id)
    pid, aid = started["processing_id"], started["attempt_id"]
    results: dict[str, Any] = {}
    try:
        for name in ORDER:
            fn = STEPS[name]
            results[name] = run_processing_step(pid, partial(_call, fn, pid, aid), aid, name)
    except HealthLakeError as exc:
        finish_attempt(aid, exc)
        exc.details.update({"processing_id": pid, "attempt_id": aid})
        raise
    except Exception as exc:
        finish_attempt(aid, HealthLakeError(repr(exc)[:300], code="unexpected"))
        raise
    final = finish_attempt(aid)
    return {
        "batch_id": batch_id,
        "processing_id": pid,
        "attempt_id": aid,
        "status": final["status"],
        "counters": results.get("classify", {}),
    }
