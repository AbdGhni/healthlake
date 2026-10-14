"""Step load: atomic Silver load of one processing.

One transaction: lock processing row, re-check status, COPY each normalized table into a temp
staging table, validate staging, insert (ON CONFLICT DO NOTHING for content-addressed rows),
mark the processing loaded. Any error rolls everything back.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg import sql

from healthlake.errors import HealthLakeError
from healthlake.ingestion.registry import set_processing_status
from healthlake.normalization.project import TABLES
from healthlake.observability import log_event
from healthlake.pipelines.workspace import Workspace
from healthlake.testing import crashpoint

ORDER = list(TABLES)  # parents before children


def load(conn: psycopg.Connection, pid: str, ws: Workspace) -> dict[str, Any]:
    done = ws.done("normalize")
    with conn.transaction():
        row = conn.execute("SELECT status FROM ctl.processing WHERE processing_id=%s FOR UPDATE", (pid,)).fetchone()
        if row is None:
            raise HealthLakeError(f"unknown processing {pid}", code="unknown_processing")
        if row[0] == "loaded":
            return {"processing_id": pid, "status": "loaded", "idempotent": True}
        if row[0] != "normalized" or done is None:
            raise HealthLakeError(f"processing must be normalized (is {row[0]})", code="wrong_state")
        inserted: dict[str, int] = {}
        for i, table in enumerate(ORDER):
            schema, name = table.split(".")
            tmp = f"stg_{name}"
            cols = TABLES[table]
            conn.execute(
                sql.SQL("CREATE TEMP TABLE {} (LIKE {}.{} INCLUDING DEFAULTS) ON COMMIT DROP").format(
                    sql.Identifier(tmp), sql.Identifier(schema), sql.Identifier(name)
                )
            )
            copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
                sql.Identifier(tmp), sql.SQL(",").join(map(sql.Identifier, cols))
            )
            n = 0
            with (
                conn.cursor().copy(copy_sql) as cp,
                ws.path(f"norm_{table}.ndjson").open(encoding="utf-8") as f,
            ):
                for line in f:
                    cp.write_row(json.loads(line))
                    n += 1
            if n != done["rows"][table]:
                raise HealthLakeError(f"staging count mismatch for {table}", code="staging_mismatch")
            if i == len(ORDER) // 2:
                crashpoint("during_load")
            cur = conn.execute(
                sql.SQL("INSERT INTO {}.{} ({cols}) SELECT {cols} FROM {} ON CONFLICT DO NOTHING").format(
                    sql.Identifier(schema),
                    sql.Identifier(name),
                    sql.Identifier(tmp),
                    cols=sql.SQL(",").join(map(sql.Identifier, cols)),
                )
            )
            inserted[table] = cur.rowcount
        _validate_staging(conn, pid)
        set_processing_status(conn, pid, "loaded", counters={"silver_rows_inserted": inserted})
        log_event("silver_loaded", conn=conn, processing_id=pid, payload={"inserted": inserted})
    crashpoint("after_silver_commit_before_return")
    return {"processing_id": pid, "status": "loaded", "inserted": inserted}


def _validate_staging(conn: psycopg.Connection, pid: str) -> None:
    """Post-insert checks inside the transaction; a failure rolls the load back."""
    checks = {
        "processing_resource_without_version": (
            "SELECT count(*) FROM silver.processing_resource pr LEFT JOIN silver.resource_version rv"
            " USING (resource_version_id) WHERE pr.processing_id=%s AND rv.resource_version_id IS NULL"
        ),
        "accepted_occurrence_without_version": (
            "SELECT count(*) FROM bronze.resource_occurrence o WHERE o.processing_id=%s"
            " AND o.outcome <> 'rejected' AND o.resource_version_id IS NULL"
        ),
        "required_subject_missing": (
            "SELECT count(*) FROM silver.processing_resource pr JOIN silver.observation o USING (resource_version_id)"
            " WHERE pr.processing_id=%s AND o.patient_entity_id IS NULL"
        ),
    }
    for name, q in checks.items():
        r = conn.execute(q, (pid,)).fetchone()
        if r and r[0]:
            raise HealthLakeError(f"staging validation failed: {name}={r[0]}", code="staging_invalid")
