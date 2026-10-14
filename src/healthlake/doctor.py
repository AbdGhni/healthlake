"""Environment checks reported as JSON."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

import psycopg

from healthlake.config import ConfigError, paths
from healthlake.errors import TransientError


def run_doctor() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        from healthlake.db import connect

        with connect("ingest") as conn:
            row = conn.execute("SELECT current_setting('server_version'), current_user").fetchone()
            checks["database"] = {"ok": True, "server_version": row[0] if row else None}
            mig = conn.execute("SELECT count(*) FROM public.healthlake_migration").fetchone()
            checks["migrations_applied"] = mig[0] if mig else 0
    except ConfigError as exc:
        checks["database"] = {"ok": False, "error": str(exc)}
    except psycopg.OperationalError as exc:
        raise TransientError(f"database unreachable: {type(exc).__name__}", code="db_unreachable") from None
    except psycopg.Error as exc:
        checks["database"] = {"ok": False, "error": type(exc).__name__}
    java = shutil.which("java")
    checks["java"] = {"ok": java is not None}
    if java:
        res = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=30, check=False)
        checks["java"]["version"] = next((ln for ln in res.stderr.splitlines() if "version" in ln), None)
    try:
        p = paths()
        checks["paths"] = {k: {"path": str(v), "exists": v.exists()} for k, v in vars(p).items()}
    except ConfigError as exc:
        checks["paths"] = {"error": str(exc)}
    return {"checks": checks}
