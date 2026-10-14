from __future__ import annotations

from pathlib import Path
from typing import Any

from healthlake.db import connect
from healthlake.errors import HealthLakeError
from healthlake.ingestion.registry import discover
from healthlake.pipelines.runner import limits
from healthlake.pipelines.steps import ingest_batch


def run(landing: Path, batch_id: str) -> dict[str, Any]:
    """Discover then ingest one batch; returns the result or the error as a dict."""
    with connect("ingest", autocommit=True) as conn:
        discover(conn, landing, limits())
    try:
        return {"ok": True, **ingest_batch(batch_id)}
    except HealthLakeError as exc:
        return {"ok": False, "error_code": exc.code, "exit_code": int(exc.exit_code), **exc.details}


def issues(cause: str | None = None) -> list[tuple[Any, ...]]:
    with connect("owner") as conn:
        if cause:
            return list(
                conn.execute(
                    "SELECT check_id, severity, cause_code, locator FROM quality.issue WHERE cause_code=%s",
                    (cause,),
                ).fetchall()
            )
        return list(conn.execute("SELECT check_id, severity, cause_code, locator FROM quality.issue").fetchall())


def one(sql: str, *params: Any) -> Any:
    with connect("owner") as conn:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
