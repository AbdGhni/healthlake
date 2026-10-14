"""Ordered, checksummed SQL migrations applied under an advisory lock."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(
    os.environ.get("HEALTHLAKE_MIGRATIONS_DIR")
    or Path(__file__).resolve().parents[3] / "infrastructure" / "postgres" / "migrations"
)
LOCK_KEY = 72_001_001


class MigrationError(RuntimeError):
    pass


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    files = sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    if not files:
        raise MigrationError(f"no migrations found in {directory}")
    return files


def apply_migrations(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    applied: list[str] = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.healthlake_migration ("
            " name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done: dict[str, str] = dict(conn.execute("SELECT name, sha256 FROM public.healthlake_migration").fetchall())
        for path in migration_files(directory):
            body = path.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            if path.name in done:
                if done[path.name] != digest:
                    raise MigrationError(f"migration {path.name} changed after being applied")
                continue
            conn.execute(body.decode("utf-8"))
            conn.execute(
                "INSERT INTO public.healthlake_migration (name, sha256) VALUES (%s, %s)", (path.name, digest)
            )
            applied.append(path.name)
    return applied
