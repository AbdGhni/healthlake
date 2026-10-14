"""Read-only database access for the API (SQLAlchemy engine on psycopg 3, role healthlake_api)."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import psycopg
from sqlalchemy import Engine, create_engine, event, text

from healthlake.config import db_config

SCHEMA_RE = re.compile(r"^release_[0-9a-f]{16}$")


@lru_cache(maxsize=1)
def engine() -> Engine:
    cfg = db_config("api")
    eng = create_engine(
        "postgresql+psycopg://",
        creator=lambda: psycopg.connect(cfg.conninfo(), application_name="healthlake-api", connect_timeout=5),
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=600,
    )

    @event.listens_for(eng, "connect")
    def _session_settings(dbapi_conn: Any, _rec: Any) -> None:
        with dbapi_conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute("SET statement_timeout = '10s'")
        dbapi_conn.commit()

    return eng


def quote_schema(schema: str) -> str:
    """Schema names come from ctl.release, never from the request; re-checked before quoting."""
    if not SCHEMA_RE.match(schema):
        raise ValueError("unexpected schema name")
    return f'"{schema}"'


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with engine().connect() as conn:
        res = conn.execute(text(sql), params or {})
        return [dict(r._mapping) for r in res]


def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None
