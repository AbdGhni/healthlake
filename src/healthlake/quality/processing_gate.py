"""Step classify: persist quarantine issues and decide whether a processing may be loaded.

Policy (demonstration thresholds, not medical thresholds; see docs/quality-catalog.md):
  - any fatal issue (unparseable file, identity conflict, content conflict, invalid update) -> blocked
  - rejected new resources / received new resources > 1 % -> blocked
  - reconciliation: received == accepted + deduplicated + rejected + out_of_scope, else blocked
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from healthlake.errors import ConflictError, HealthLakeError, QualityBlockedError
from healthlake.ingestion.registry import processing_row, set_processing_status, status_at_least
from healthlake.observability import log_event
from healthlake.pipelines.workspace import Workspace

MAX_REJECT_RATE = 0.01


def classify(conn: psycopg.Connection, pid: str, attempt_id: str | None, ws: Workspace) -> dict[str, Any]:
    p = processing_row(conn, pid)
    if p["status"] == "blocked":
        raise QualityBlockedError(
            "processing already blocked", code="processing_blocked", reason=p["counters"].get("block_reason")
        )
    if status_at_least(p["status"], "validated"):
        return {"processing_id": pid, "status": p["status"], "idempotent": True}
    summary = ws.done("resolve")
    if summary is None:
        raise HealthLakeError("resolve must run before classify", code="wrong_state")
    file_issues: list[dict[str, Any]] = ws.read_json("file_issues.json")
    fatal = list(summary["fatal_issues"]) + [i for i in file_issues if i["severity"] == "fatal"]
    loc_by_n: dict[int, str] = {}
    rows: list[tuple[Any, ...]] = []
    for d in ws.ndjson("decisions.ndjson"):
        loc_by_n[d["n"]] = d["issues"][0]["locator"] if d["issues"] else ""
    for d in ws.ndjson("decisions.ndjson"):
        cause_loc = loc_by_n.get(d["caused_by_n"]) if d["caused_by_n"] else None
        for i in d["issues"]:
            rows.append(
                (
                    i["file_sha256"],
                    i["locator"],
                    d["type"],
                    d["id"],
                    i["check_id"],
                    i["severity"],
                    i["cause_code"],
                    i["message"][:1000],
                    cause_loc if i["cause_code"] == "dependency_rejected" else None,
                )
            )
    hl7_issues: list[dict[str, Any]] = ws.read_json("hl7_issues.json") if ws.path("hl7_issues.json").exists() else []
    hl7 = ws.done("hl7") or {"status": "skipped"}
    for i in fatal + [i for i in file_issues if i["severity"] != "fatal"] + hl7_issues:
        rows.append(
            (
                i.get("file_sha256"),
                i.get("locator"),
                None,
                None,
                i["check_id"],
                i["severity"],
                i["cause_code"],
                i["message"][:1000],
                None,
            )
        )

    received, rejected_new, received_new = (
        summary["received"],
        summary["rejected_new"],
        summary["received_new"],
    )
    reject_rate = (rejected_new / received_new) if received_new else 0.0
    recon_ok = received == (
        summary["accepted"] + summary["deduplicated"] + summary["rejected"] + summary["out_of_scope"]
    )
    conflicts = [f for f in fatal if f["cause_code"] in ("identity_conflict", "content_conflict")]
    checks = [
        ("reconciliation.occurrences", recon_ok, 0 if recon_ok else 1, 0, {}),
        (
            "format.fatal_files",
            not [f for f in fatal if f["check_id"].startswith("format.")],
            len([f for f in fatal if f["check_id"].startswith("format.")]),
            0,
            {},
        ),
        ("identity.conflicts", not conflicts, len(conflicts), 0, {}),
        ("identity.invalid_updates", summary["invalid_updates"] == 0, summary["invalid_updates"], 0, {}),
        (
            "quarantine.reject_rate_new",
            reject_rate <= MAX_REJECT_RATE,
            round(reject_rate, 6),
            MAX_REJECT_RATE,
            {"rejected_new": rejected_new, "received_new": received_new},
        ),
    ]
    blocked = [c[0] for c in checks if not c[1]]
    audit = ("fhir.hl7_validator_sample", hl7.get("unexplained_errors", 0), hl7)
    counters = {
        k: summary[k]
        for k in (
            "received",
            "accepted",
            "deduplicated",
            "rejected",
            "out_of_scope",
            "received_new",
            "rejected_new",
            "invalid_updates",
        )
    }
    counters["reject_rate_new"] = round(reject_rate, 6)
    with conn.transaction():
        conn.execute("SELECT 1 FROM ctl.processing WHERE processing_id=%s FOR UPDATE", (pid,))
        again = processing_row(conn, pid)
        if again["status"] != p["status"]:
            raise HealthLakeError("processing changed concurrently", code="concurrent_attempt")
        conn.execute(
            "CREATE TEMP TABLE tmp_issue (file_sha256 text, locator text, resource_type text,"
            " source_resource_id text, check_id text, severity text, cause_code text, message text,"
            " cause_locator text) ON COMMIT DROP"
        )
        with conn.cursor().copy("COPY tmp_issue FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
        conn.execute(
            "INSERT INTO quality.issue (processing_id, attempt_id, file_sha256, locator, resource_type,"
            " source_resource_id, check_id, severity, cause_code, message)"
            " SELECT %s, %s, file_sha256, locator, resource_type, source_resource_id, check_id, severity,"
            " cause_code, message FROM tmp_issue",
            (pid, attempt_id),
        )
        conn.execute(
            "UPDATE quality.issue d SET caused_by_issue_id = c.issue_id"
            " FROM tmp_issue t, LATERAL (SELECT min(issue_id) AS issue_id FROM quality.issue c"
            "   WHERE c.processing_id=%s AND c.locator=t.cause_locator AND c.cause_code <> 'dependency_rejected') c"
            " WHERE t.cause_locator IS NOT NULL AND d.processing_id=%s AND d.locator=t.locator"
            "   AND d.cause_code='dependency_rejected'",
            (pid, pid),
        )
        for check_id, ok, observed, threshold, details in checks:
            conn.execute(
                "INSERT INTO quality.check_result (scope, scope_id, check_id, status, observed, threshold, details)"
                " VALUES ('processing', %s, %s, %s, %s, %s, %s) ON CONFLICT (scope, scope_id, check_id) DO UPDATE"
                " SET status=EXCLUDED.status, observed=EXCLUDED.observed, details=EXCLUDED.details,"
                " evaluated_at=now()",
                (pid, check_id, "pass" if ok else "fail", observed, threshold, Jsonb(details)),
            )
        conn.execute(
            "INSERT INTO quality.check_result (scope, scope_id, check_id, status, observed, threshold, details)"
            " VALUES ('processing', %s, %s, %s, %s, NULL, %s) ON CONFLICT (scope, scope_id, check_id) DO UPDATE"
            " SET status=EXCLUDED.status, observed=EXCLUDED.observed, details=EXCLUDED.details, evaluated_at=now()",
            (
                pid,
                audit[0],
                "skipped" if audit[2].get("status") == "skipped" else ("warn" if audit[1] else "pass"),
                audit[1],
                Jsonb(audit[2]),
            ),
        )
        if blocked:
            counters["block_reason"] = ",".join(blocked)
            set_processing_status(conn, pid, "blocked", reason=",".join(blocked), counters=counters)
            log_event(
                "processing_blocked",
                level="error",
                conn=conn,
                processing_id=pid,
                attempt_id=attempt_id,
                payload={"failed_checks": blocked, **counters},
            )
        else:
            set_processing_status(conn, pid, "validated", counters=counters)
            log_event("processing_classified", conn=conn, processing_id=pid, attempt_id=attempt_id, payload=counters)
    if blocked:
        err = ConflictError if ("identity.conflicts" in blocked and len(blocked) == 1) else QualityBlockedError
        raise err(
            f"processing blocked by {', '.join(blocked)}",
            code="processing_blocked",
            failed_checks=blocked,
            counters=counters,
        )
    return {"processing_id": pid, "status": "validated", "issues_recorded": len(rows), **counters}
