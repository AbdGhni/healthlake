"""quality-gate: decide whether a built release may be published. Results persisted per check."""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from healthlake.db import connect
from healthlake.errors import ContractError, QualityBlockedError
from healthlake.observability import log_event, set_context
from healthlake.release.build import REQUIRED_MODELS, release_artifacts_dir
from healthlake.testing import crashpoint

# snapshot resource type -> (model, key column) for release reconciliation
RECONCILE = {
    "Patient": "dim_patient",
    "Organization": "dim_organization",
    "Practitioner": "dim_practitioner",
    "Encounter": "fct_encounter",
    "Condition": "fct_condition",
    "Observation": "fct_observation",
    "MedicationRequest": "fct_medication_request",
}


def existing_relations(conn: psycopg.Connection, schema: str) -> set[str]:
    rows = conn.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace"
        " WHERE n.nspname=%s AND c.relkind IN ('r','v','m')",
        (schema,),
    ).fetchall()
    return {r[0] for r in rows}


def quality_gate(rid: str) -> dict[str, Any]:
    set_context(release_id=rid)
    with connect("publish", autocommit=True) as conn:
        row = conn.execute("SELECT status, schema_name FROM ctl.release WHERE release_id=%s", (rid,)).fetchone()
        if row is None:
            raise ContractError("unknown release", code="unknown_release")
        status, schema = row
        if status in ("gate_passed", "published"):
            return {"release_id": rid, "status": status, "idempotent": True}
        if status == "gate_failed":
            raise QualityBlockedError("release gate already failed", code="release_gate_failed", release_id=rid)
        if status != "built":
            raise ContractError(f"release must be built (is {status})", code="wrong_state")
        meta = json.loads((release_artifacts_dir(rid) / "release.json").read_text())
        dbt = meta["dbt"]
        present = existing_relations(conn, schema)
        missing = sorted(set(REQUIRED_MODELS) - present)
        snap = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT resource_type, count(*) FROM silver.snapshot_member WHERE snapshot_id=%s GROUP BY 1", (rid,)
            ).fetchall()
        }
        recon: dict[str, Any] = {}
        if not missing:
            for rtype, model in RECONCILE.items():
                q = sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(model))
                got = conn.execute(q).fetchone()
                n = got[0] if got else 0
                if n != snap.get(rtype, 0):
                    recon[model] = {"gold": n, "snapshot": snap.get(rtype, 0)}
        not_passed = conn.execute(
            "SELECT count(*) FROM ctl.release_processing rp JOIN quality.check_result c"
            " ON c.scope='processing' AND c.scope_id=rp.processing_id"
            " WHERE rp.release_id=%s AND c.status='fail'",
            (rid,),
        ).fetchone()
        checks = [
            (
                "dbt.tests",
                dbt["tests_failed"] == 0 and dbt["skipped"] == 0,
                dbt["tests_failed"] + dbt["skipped"],
                0,
                {"passed": dbt["tests_passed"], "failed": dbt["tests_failed"], "skipped": dbt["skipped"]},
            ),
            ("dbt.models", dbt["model_errors"] == 0, dbt["model_errors"], 0, {"models": dbt["models"]}),
            ("release.schema_complete", not missing, len(missing), 0, {"missing": missing}),
            (
                "release.snapshot_dangling_references",
                meta["snapshot"]["dangling_references"] == 0,
                meta["snapshot"]["dangling_references"],
                0,
                {},
            ),
            ("release.gold_reconciles_snapshot", not missing and not recon, len(recon), 0, recon),
            (
                "release.processings_passed",
                (not_passed[0] if not_passed else 0) == 0,
                not_passed[0] if not_passed else 0,
                0,
                {},
            ),
        ]
        failed = [c[0] for c in checks if not c[1]]
        with conn.transaction():
            for check_id, ok, observed, threshold, details in checks:
                conn.execute(
                    "INSERT INTO quality.check_result (scope, scope_id, check_id, status, observed, threshold,"
                    " details) VALUES ('release', %s, %s, %s, %s, %s, %s) ON CONFLICT (scope, scope_id, check_id)"
                    " DO UPDATE SET status=EXCLUDED.status, observed=EXCLUDED.observed, details=EXCLUDED.details,"
                    " evaluated_at=now()",
                    (rid, check_id, "pass" if ok else "fail", observed, threshold, Jsonb(details)),
                )
            new_status = "gate_failed" if failed else "gate_passed"
            conn.execute(
                "UPDATE ctl.release SET status=%s, status_reason=%s, gate_result=%s WHERE release_id=%s",
                (new_status, ",".join(failed) or None, Jsonb({c[0]: "pass" if c[1] else "fail" for c in checks}), rid),
            )
            log_event(
                "release_gate",
                level="error" if failed else "info",
                conn=conn,
                release_id=rid,
                payload={"failed_checks": failed},
            )
    crashpoint("after_gate_before_publish")
    if failed:
        raise QualityBlockedError(
            f"release gate failed: {', '.join(failed)}",
            code="release_gate_failed",
            release_id=rid,
            failed_checks=failed,
        )
    return {"release_id": rid, "status": "gate_passed", "checks": {c[0]: "pass" for c in checks}}
