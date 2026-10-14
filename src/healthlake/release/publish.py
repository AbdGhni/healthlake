"""publish: atomic activation of a gate-passed release; purge beyond retention.

In one transaction (publish role): lock the release row, check the gate, check the schema is complete,
grant read on the Gold marts to the API role, mark the release published, point ctl.active_release at it.
A failure anywhere leaves the previous active release untouched.
"""

from __future__ import annotations

import os
from typing import Any

from psycopg import sql

from healthlake.db import connect
from healthlake.errors import ContractError, QualityBlockedError
from healthlake.observability import log_event, set_context
from healthlake.release.build import REQUIRED_MODELS
from healthlake.release.gate import existing_relations
from healthlake.testing import crashpoint


def publish(rid: str) -> dict[str, Any]:
    set_context(release_id=rid)
    with connect("publish", autocommit=True) as conn:
        with conn.transaction():
            row = conn.execute(
                "SELECT status, schema_name FROM ctl.release WHERE release_id=%s FOR UPDATE", (rid,)
            ).fetchone()
            if row is None:
                raise ContractError("unknown release", code="unknown_release")
            status, schema = row
            active = conn.execute("SELECT release_id FROM ctl.active_release FOR UPDATE").fetchone()
            if status == "published" and active and active[0] == rid:
                return {"release_id": rid, "status": "published", "active": True, "idempotent": True}
            if status not in ("gate_passed", "published"):
                raise QualityBlockedError(
                    f"release is {status}, not gate_passed", code="release_not_publishable", release_id=rid
                )
            missing = sorted(set(REQUIRED_MODELS) - existing_relations(conn, schema))
            if missing:
                raise QualityBlockedError("release schema incomplete", code="release_incomplete", missing=missing)
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO hl_api_read").format(sql.Identifier(schema)))
            for model in REQUIRED_MODELS:
                conn.execute(
                    sql.SQL("GRANT SELECT ON {}.{} TO hl_api_read").format(
                        sql.Identifier(schema), sql.Identifier(model)
                    )
                )
            conn.execute(
                "UPDATE ctl.release SET status='published', published_at=coalesce(published_at, now())"
                " WHERE release_id=%s",
                (rid,),
            )
            previous = active[0] if active else None
            conn.execute("UPDATE ctl.active_release SET release_id=%s, activated_at=now()", (rid,))
            log_event("release_published", conn=conn, release_id=rid, payload={"previous_release_id": previous})
        crashpoint("after_publish_commit_before_return")
        purged = purge_old_releases(conn)
    return {"release_id": rid, "status": "published", "active": True, "previous_release_id": previous, "purged": purged}


def purge_old_releases(conn: Any, keep: int | None = None) -> list[str]:
    """Keep the active release and the `keep` most recent other published releases; drop older schemas."""
    keep = keep if keep is not None else int(os.environ.get("HEALTHLAKE_RELEASE_RETENTION", "3"))
    rows = conn.execute(
        "SELECT r.release_id, r.schema_name FROM ctl.release r WHERE r.status='published'"
        " AND r.release_id IS DISTINCT FROM (SELECT release_id FROM ctl.active_release)"
        " ORDER BY r.published_at DESC OFFSET %s",
        (keep,),
    ).fetchall()
    purged = []
    for rid, schema in rows:
        with conn.transaction():
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
            conn.execute("UPDATE ctl.release SET status='purged', purged_at=now() WHERE release_id=%s", (rid,))
            log_event("release_purged", conn=conn, release_id=rid)
        purged.append(rid)
    return purged
