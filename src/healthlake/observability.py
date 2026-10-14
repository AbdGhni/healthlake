"""Structured JSON logs on stderr and the ctl.event table. Never logs secrets or resource bodies."""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

_CONTEXT: dict[str, str] = {}


def set_context(**ids: str | None) -> None:
    """Replace the log context (ids attached to every log line of the current command)."""
    _CONTEXT.clear()
    for k, v in ids.items():
        if v:
            _CONTEXT[k] = v


_SECRET_PATTERNS = [
    re.compile(r"(password\s*=\s*)('[^']*'|\S+)", re.IGNORECASE),
    re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)"),
    re.compile(r"(X-API-Key[\"']?\s*[:=]\s*[\"']?)([^\s\"',]+)", re.IGNORECASE),
]


def redact(text: str) -> str:
    """Remove credentials that libraries may echo in error messages."""
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: m.group(1) + "***" + (m.group(3) if m.lastindex and m.lastindex >= 3 else ""), text)
    return text


def log(event: str, level: str = "info", **fields: Any) -> None:
    rec = {
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "level": level,
        "event": event,
        **_CONTEXT,
        **fields,
    }
    sys.stderr.write(redact(json.dumps(rec, separators=(",", ":"), default=str, sort_keys=True)) + "\n")


def log_event(
    event: str,
    level: str = "info",
    conn: psycopg.Connection | None = None,
    batch_id: str | None = None,
    processing_id: str | None = None,
    attempt_id: str | None = None,
    release_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    ids = {
        "batch_id": batch_id,
        "processing_id": processing_id,
        "attempt_id": attempt_id,
        "release_id": release_id,
    }
    log(event, level, **{k: v for k, v in ids.items() if v}, **(payload or {}))
    if conn is not None:
        conn.execute(
            "INSERT INTO ctl.event (event, level, batch_id, processing_id, attempt_id, release_id, payload)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (event, level, batch_id, processing_id, attempt_id, release_id, Jsonb(payload or {})),
        )


class Timer:
    def __enter__(self) -> Timer:
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.seconds = round(time.perf_counter() - self.start, 3)
