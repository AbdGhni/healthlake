"""Database helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from healthlake.config import db_config


@contextmanager
def connect(role: str, autocommit: bool = False) -> Iterator[psycopg.Connection]:
    cfg = db_config(role)
    conn = psycopg.connect(cfg.conninfo(), autocommit=autocommit, application_name=f"healthlake-{role}")
    try:
        yield conn
    finally:
        conn.close()
