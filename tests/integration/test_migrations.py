from __future__ import annotations

import shutil
from pathlib import Path

import psycopg
import pytest

from healthlake.db import connect
from healthlake.db.init import init_database
from healthlake.db.migrate import MIGRATIONS_DIR, MigrationError, apply_migrations

pytestmark = pytest.mark.db


def test_init_is_idempotent(fresh_db: dict[str, str]) -> None:
    first = init_database()
    second = init_database()
    assert len(first["migrations_applied"]) >= 5
    assert second["migrations_applied"] == []
    assert second["users_created"] == []


def test_changed_migration_is_rejected(fresh_db: dict[str, str], tmp_path: Path) -> None:
    copy = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, copy)
    with connect("owner", autocommit=True) as conn:
        apply_migrations(conn, copy)
        first = sorted(copy.glob("*.sql"))[0]
        first.write_text(first.read_text() + "\n-- edited\n")
        with pytest.raises(MigrationError, match="changed after being applied"):
            apply_migrations(conn, copy)


def test_api_role_cannot_read_silver_or_bronze(initialized_db: dict[str, str]) -> None:
    with connect("api") as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM silver.resource_version LIMIT 1")
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM bronze.file LIMIT 1")


def test_ingest_role_cannot_create_schema(initialized_db: dict[str, str]) -> None:
    with connect("ingest") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("CREATE SCHEMA release_0000000000000000")


def test_only_ingest_can_refresh_snapshot_statistics(initialized_db: dict[str, str]) -> None:
    """The ingestion role analyzes the snapshot tables through one SECURITY DEFINER function (migration 0009)."""
    with connect("ingest") as conn:
        conn.execute("SELECT silver.analyze_snapshot()")
    with connect("api") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT silver.analyze_snapshot()")


def test_active_release_is_singleton(initialized_db: dict[str, str]) -> None:
    with connect("owner") as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO ctl.active_release (singleton) VALUES (false)")
        conn.rollback()
        rows = conn.execute("SELECT release_id FROM ctl.active_release").fetchall()
        assert rows == [(None,)]
