"""Shared fixtures. DB tests need HEALTHLAKE_TEST_ADMIN_DSN (a superuser DSN on a disposable server)."""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

ROLES = ("owner", "ingest", "dbt", "publish", "api")


def _admin_dsn() -> str:
    dsn = os.environ.get("HEALTHLAKE_TEST_ADMIN_DSN")
    if not dsn:
        pytest.skip("HEALTHLAKE_TEST_ADMIN_DSN not set")
    return dsn


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Create an empty database owned by a superuser-like owner role, point HEALTHLAKE_* env at it."""
    admin = _admin_dsn()
    name = f"hl_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        host, port = conn.info.host, conn.info.port
        conn.execute(
            "DO $$BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='healthlake_owner') "
            "THEN CREATE ROLE healthlake_owner LOGIN SUPERUSER; END IF; END$$"
        )
        conn.execute(sql.SQL("CREATE DATABASE {} OWNER healthlake_owner").format(sql.Identifier(name)))
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    for role in ROLES:
        f = secret_dir / role
        f.write_text(secrets.token_urlsafe(24))
        monkeypatch.setenv(f"HEALTHLAKE_DB_{role.upper()}_PASSWORD_FILE", str(f))
    monkeypatch.setenv("HEALTHLAKE_DB_HOST", host)
    monkeypatch.setenv("HEALTHLAKE_DB_PORT", str(port))
    monkeypatch.setenv("HEALTHLAKE_DB_NAME", name)
    try:
        yield {"name": name}
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def initialized_db(fresh_db: dict[str, str]) -> dict[str, str]:
    from healthlake.db.init import init_database

    init_database()
    return fresh_db


@pytest.fixture
def lake(initialized_db: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Initialized DB + empty landing/lake/work dirs + sources registered. HL7 audit disabled for speed."""
    dirs = {k: tmp_path / k for k in ("landing", "lake", "work", "artifacts")}
    for k, p in dirs.items():
        p.mkdir()
        monkeypatch.setenv(f"HEALTHLAKE_{k.upper()}_DIR", str(p))
    monkeypatch.delenv("HEALTHLAKE_HL7_VALIDATOR_JAR", raising=False)
    from healthlake.db import connect
    from healthlake.ingestion.registry import ensure_sources
    from healthlake.pipelines.runner import sources_config

    with connect("ingest", autocommit=True) as conn:
        ensure_sources(conn, sources_config()["sources"])
    return dirs


def q(sql_text: str, *params: object) -> list[tuple[object, ...]]:
    from healthlake.db import connect

    with connect("owner") as conn:
        return list(conn.execute(sql_text, params).fetchall())
