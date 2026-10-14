"""Batch discovery, registration, verification, processing/attempt bookkeeping and archiving."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from healthlake.errors import ConflictError, ContractError, HealthLakeError
from healthlake.ids import CODE_VERSION, MAPPING_VERSION, VALIDATION_VERSION, processing_id, source_namespace
from healthlake.ingestion.manifest import MANIFEST_NAME, Limits, parse_manifest, scan_batch_dir
from healthlake.ingestion.rawstore import LocalRawStore
from healthlake.observability import log_event


def ensure_sources(conn: psycopg.Connection, sources: list[dict[str, Any]]) -> None:
    for s in sources:
        conn.execute(
            "INSERT INTO ctl.source (source_id, display_name, source_format, namespace_uuid)"
            " VALUES (%s,%s,%s,%s) ON CONFLICT (source_id) DO NOTHING",
            (s["source_id"], s["display_name"], s["source_format"], source_namespace(s["source_id"])),
        )


def find_batch_dirs(landing: Path) -> list[Path]:
    """Finalized batch dirs: landing/<source>/<rev-dir>/manifest.json, temp dirs (.tmp-*) ignored.

    Order is deterministic: source id, then directory name.
    """
    out: list[Path] = []
    if not landing.exists():
        return out
    for source_dir in sorted(p for p in landing.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for d in sorted(p for p in source_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
            if (d / MANIFEST_NAME).is_file():
                out.append(d)
    return out


def register_batch(conn: psycopg.Connection, batch_dir: Path, landing: Path, limits: Limits) -> dict[str, Any]:
    raw = (batch_dir / MANIFEST_NAME).read_bytes()
    model, logical, bid = parse_manifest(raw, limits)
    if batch_dir.parent.name != model.source_id:
        raise ContractError("batch directory does not match manifest source_id", code="manifest_invalid")
    rel = batch_dir.relative_to(landing).as_posix()
    with conn.transaction():
        src = conn.execute("SELECT 1 FROM ctl.source WHERE source_id=%s", (model.source_id,)).fetchone()
        if src is None:
            raise ContractError(f"unknown source {model.source_id}", code="unknown_source")
        existing = conn.execute(
            "SELECT batch_id FROM ctl.batch WHERE source_id=%s AND source_revision=%s",
            (model.source_id, model.source_revision),
        ).fetchone()
        if existing:
            if existing[0] != bid:
                log_event(
                    "batch_conflict",
                    level="error",
                    conn=conn,
                    batch_id=bid,
                    payload={
                        "source_id": model.source_id,
                        "revision": model.source_revision,
                        "registered_batch_id": existing[0],
                    },
                )
                raise ConflictError(
                    f"{model.source_id} revision {model.source_revision} already registered with other content",
                    code="revision_conflict",
                    batch_id=bid,
                    registered_batch_id=existing[0],
                )
            return {"batch_id": bid, "registered": False}
        conn.execute(
            "INSERT INTO ctl.batch (batch_id, source_id, source_revision, manifest, manifest_sha256, landing_path,"
            " status) VALUES (%s,%s,%s,%s,%s,%s,'registered') ON CONFLICT (batch_id) DO NOTHING",
            (
                bid,
                model.source_id,
                model.source_revision,
                Jsonb(logical),
                hashlib.sha256(raw).hexdigest(),
                rel,
            ),
        )
        log_event(
            "batch_registered",
            conn=conn,
            batch_id=bid,
            payload={"source_id": model.source_id, "revision": model.source_revision},
        )
    return {"batch_id": bid, "registered": True}


def discover(conn: psycopg.Connection, landing: Path, limits: Limits) -> dict[str, Any]:
    """Register every finalized batch. Invalid manifests are reported, never registered."""
    results: list[dict[str, Any]] = []
    for d in find_batch_dirs(landing):
        try:
            r = register_batch(conn, d, landing, limits)
            results.append({"path": d.relative_to(landing).as_posix(), **r})
        except (ContractError, ConflictError) as exc:
            results.append({"path": d.relative_to(landing).as_posix(), "error_code": exc.code, "message": str(exc)})
    pending = conn.execute(
        "SELECT b.batch_id FROM ctl.batch b WHERE b.status IN ('registered','verified','archived')"
        " AND NOT EXISTS (SELECT 1 FROM ctl.processing p WHERE p.batch_id=b.batch_id"
        "  AND p.code_version=%s AND p.mapping_version=%s AND p.validation_version=%s"
        "  AND p.status IN ('loaded','blocked'))"
        " ORDER BY b.source_id, b.source_revision",
        (CODE_VERSION, MAPPING_VERSION, VALIDATION_VERSION),
    ).fetchall()
    return {"batches": results, "pending_batch_ids": [r[0] for r in pending]}


def _batch(conn: psycopg.Connection, bid: str) -> tuple[dict[str, Any], str, str]:
    row = conn.execute("SELECT manifest, landing_path, status FROM ctl.batch WHERE batch_id=%s", (bid,)).fetchone()
    if row is None:
        raise ContractError(f"unknown batch {bid}", code="unknown_batch")
    return row[0], row[1], row[2]


def verify_batch(conn: psycopg.Connection, bid: str, landing: Path) -> dict[str, Any]:
    manifest, rel, status = _batch(conn, bid)
    if status in ("verified", "archived"):
        return {"batch_id": bid, "status": status, "idempotent": True}
    batch_dir = landing / rel
    problems: list[str] = []
    try:
        present = scan_batch_dir(batch_dir)
    except ContractError as exc:
        problems.append(str(exc))
        present = []
    declared = {f["path"]: f for f in manifest["files"]}
    undeclared = sorted(set(present) - set(declared))
    missing = sorted(set(declared) - set(present))
    if undeclared:
        problems.append(f"undeclared files: {undeclared[:5]}")
    if missing:
        problems.append(f"missing files: {missing[:5]}")
    for path, f in sorted(declared.items()):
        if path in missing:
            continue
        p = batch_dir / path
        if p.stat().st_size != f["size_bytes"]:
            problems.append(f"size mismatch: {path}")
            continue
        h = hashlib.sha256()
        with p.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                h.update(chunk)
        if h.hexdigest() != f["sha256"]:
            problems.append(f"hash mismatch: {path}")
    with conn.transaction():
        if problems:
            conn.execute(
                "UPDATE ctl.batch SET status='invalid', status_reason=%s, updated_at=now() WHERE batch_id=%s",
                ("; ".join(problems)[:2000], bid),
            )
            log_event("batch_invalid", level="error", conn=conn, batch_id=bid, payload={"problems": problems})
        else:
            conn.execute("UPDATE ctl.batch SET status='verified', updated_at=now() WHERE batch_id=%s", (bid,))
            log_event("batch_verified", conn=conn, batch_id=bid)
    if problems:
        raise ContractError("batch verification failed", code="batch_invalid", batch_id=bid, problems=problems)
    return {"batch_id": bid, "status": "verified", "files": len(declared)}


def start_attempt(conn: psycopg.Connection, bid: str, orchestrator_run_id: str | None) -> dict[str, Any]:
    pid = processing_id(bid)
    with conn.transaction():
        _batch(conn, bid)
        conn.execute(
            "INSERT INTO ctl.processing (processing_id, batch_id, code_version, mapping_version,"
            " validation_version, status) VALUES (%s,%s,%s,%s,%s,'pending') ON CONFLICT DO NOTHING",
            (pid, bid, CODE_VERSION, MAPPING_VERSION, VALIDATION_VERSION),
        )
        status = conn.execute("SELECT status FROM ctl.processing WHERE processing_id=%s", (pid,)).fetchone()
        assert status is not None
        aid = uuid.uuid4()
        conn.execute(
            "INSERT INTO ctl.attempt (attempt_id, processing_id, orchestrator_run_id, status, current_step)"
            " VALUES (%s,%s,%s,'running','start')",
            (aid, pid, orchestrator_run_id),
        )
        log_event("attempt_started", conn=conn, batch_id=bid, processing_id=pid, attempt_id=str(aid))
    return {"batch_id": bid, "processing_id": pid, "attempt_id": str(aid), "processing_status": status[0]}


def processing_row(conn: psycopg.Connection, pid: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT p.processing_id, p.batch_id, p.status, b.source_id, b.source_revision, b.manifest, b.landing_path,"
        " b.status, p.counters FROM ctl.processing p JOIN ctl.batch b USING (batch_id) WHERE p.processing_id=%s",
        (pid,),
    ).fetchone()
    if row is None:
        raise ContractError(f"unknown processing {pid}", code="unknown_processing")
    keys = [
        "processing_id",
        "batch_id",
        "status",
        "source_id",
        "source_revision",
        "manifest",
        "landing_path",
        "batch_status",
        "counters",
    ]
    return dict(zip(keys, row, strict=True))


STATUS_ORDER = ["pending", "archived", "adapted", "validated", "normalized", "loaded"]


def status_at_least(status: str, target: str) -> bool:
    return status in STATUS_ORDER and STATUS_ORDER.index(status) >= STATUS_ORDER.index(target)


def set_processing_status(
    conn: psycopg.Connection,
    pid: str,
    status: str,
    reason: str | None = None,
    counters: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "UPDATE ctl.processing SET status=%s, status_reason=%s, counters = counters || %s, updated_at=now(),"
        " loaded_at = CASE WHEN %s='loaded' THEN now() ELSE loaded_at END WHERE processing_id=%s",
        (status, reason, Jsonb(counters or {}), status, pid),
    )


def archive(conn: psycopg.Connection, pid: str, landing: Path, store: LocalRawStore) -> dict[str, Any]:
    """Copy declared files into the RawStore (by hash) and register them. Re-runnable after a crash:
    objects already stored are verified, not rewritten; registry rows use ON CONFLICT DO NOTHING."""
    p = processing_row(conn, pid)
    if status_at_least(p["status"], "archived"):
        return {"processing_id": pid, "status": p["status"], "idempotent": True}
    if p["status"] == "blocked":
        raise HealthLakeError("processing is blocked", code="processing_blocked")
    if p["batch_status"] not in ("verified", "archived"):
        raise ContractError("batch must be verified before archiving", code="batch_not_verified")
    batch_dir = landing / p["landing_path"]
    created = 0
    for f in p["manifest"]["files"]:
        with (batch_dir / f["path"]).open("rb") as src:
            if store.put_if_absent(f["sha256"], src):
                created += 1
    from healthlake.testing import crashpoint

    crashpoint("after_archive_before_status")
    with conn.transaction():
        for f in p["manifest"]["files"]:
            conn.execute(
                "INSERT INTO bronze.file (sha256, size_bytes, mime_type, storage_key, last_verified_at)"
                " VALUES (%s,%s,%s,%s,now()) ON CONFLICT (sha256) DO UPDATE SET last_verified_at=now()",
                (f["sha256"], f["size_bytes"], f["mime_type"], store.key(f["sha256"])),
            )
            conn.execute(
                "INSERT INTO bronze.batch_file (batch_id, relative_path, sha256) VALUES (%s,%s,%s)"
                " ON CONFLICT DO NOTHING",
                (p["batch_id"], f["path"], f["sha256"]),
            )
        conn.execute("UPDATE ctl.batch SET status='archived', updated_at=now() WHERE batch_id=%s", (p["batch_id"],))
        set_processing_status(conn, pid, "archived")
        log_event(
            "batch_archived",
            conn=conn,
            batch_id=p["batch_id"],
            processing_id=pid,
            payload={"files": len(p["manifest"]["files"]), "objects_created": created},
        )
    return {"processing_id": pid, "status": "archived", "objects_created": created}


def dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)
