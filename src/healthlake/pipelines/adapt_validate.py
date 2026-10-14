"""Steps adapt and validate."""

from __future__ import annotations

from typing import Any

import psycopg

from healthlake.adapters.base import AdaptedResource, Issue
from healthlake.adapters.fhir_bundle import adapt_bundle_file
from healthlake.adapters.horizon import adapt_csv_batch, adapt_json_file
from healthlake.errors import HealthLakeError
from healthlake.ingestion.manifest import Limits
from healthlake.ingestion.rawstore import LocalRawStore
from healthlake.ingestion.registry import processing_row, set_processing_status, status_at_least
from healthlake.observability import log_event
from healthlake.pipelines.workspace import Workspace
from healthlake.validation.structural import validate_resource


def _require(p: dict[str, Any], status: str) -> None:
    if p["status"] == "blocked":
        raise HealthLakeError("processing is blocked", code="processing_blocked")
    if not status_at_least(p["status"], status):
        raise HealthLakeError(f"processing must be at least {status} (is {p['status']})", code="wrong_state")


def adapt(conn: psycopg.Connection, pid: str, store: LocalRawStore, ws: Workspace, limits: Limits) -> dict[str, Any]:
    p = processing_row(conn, pid)
    _require(p, "archived")
    done = ws.done("adapt")
    if done is not None:
        if not status_at_least(p["status"], "adapted"):
            with conn.transaction():
                set_processing_status(conn, pid, "adapted", counters={"received": done["received"]})
        return {**done, "idempotent": True}
    manifest = p["manifest"]
    fmt = manifest["source_format"]
    file_issues: list[Issue] = []
    received = 0
    with ws.ndjson_writer("adapted.ndjson") as out:

        def emit(items: Any) -> None:
            nonlocal received
            for item in items:
                if isinstance(item, Issue):
                    file_issues.append(item)
                    continue
                assert isinstance(item, AdaptedResource)
                received += 1
                if received > limits.max_resources:
                    raise HealthLakeError("resource limit exceeded", code="limit_exceeded")
                out.write(item.to_record(received))

        if fmt == "fhir-r4-bundle":
            for f in manifest["files"]:
                emit(adapt_bundle_file(f["sha256"], f["path"], store.get(f["sha256"])))
        elif fmt == "horizon-csv-v1":
            emit(adapt_csv_batch([(f["path"], f["sha256"], store.get(f["sha256"])) for f in manifest["files"]]))
        elif fmt == "horizon-json-v1":
            for f in manifest["files"]:
                emit(adapt_json_file(f["path"], f["sha256"], store.get(f["sha256"])))
        else:
            raise HealthLakeError(f"no adapter for {fmt}", code="no_adapter")
    ws.write_json("file_issues.json", [vars(i) for i in file_issues])
    summary = {"received": received, "file_issues": len(file_issues)}
    ws.mark_done("adapt", summary)
    with conn.transaction():
        set_processing_status(conn, pid, "adapted", counters={"received": received})
        log_event("adapted", conn=conn, processing_id=pid, payload=summary)
    return summary


def validate(conn: psycopg.Connection, pid: str, ws: Workspace, store: LocalRawStore | None = None) -> dict[str, Any]:
    p = processing_row(conn, pid)
    _require(p, "adapted")
    done = ws.done("validate")
    if done is not None:
        return {**done, "idempotent": True}
    with_issues = 0
    errors = 0
    with ws.ndjson_writer("validation.ndjson") as out:
        for rec in ws.ndjson("adapted.ndjson"):
            issues = list(rec["issues"])
            if rec["resource"]:
                issues += [vars(i) for i in validate_resource(rec["type"], rec["resource"], rec["loc"], rec["file"])]
            if issues:
                with_issues += 1
                errors += sum(1 for i in issues if i["severity"] in ("error", "fatal"))
                out.write({"n": rec["n"], "issues": issues})
    summary: dict[str, Any] = {
        "resources_with_issues": with_issues,
        "error_issues": errors,
        "validator": "structural-val-1",
    }
    if ws.done("hl7") is None and store is not None:
        from healthlake.validation.hl7 import run_audit

        summary["hl7_audit"] = run_audit(p["manifest"], ws, store.path)
    elif ws.done("hl7") is not None:
        summary["hl7_audit"] = ws.done("hl7")
    ws.mark_done("validate", summary)
    log_event("validated", processing_id=pid, payload=summary)
    return summary
