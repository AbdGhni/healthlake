"""Database bootstrap: login users from secret files, group membership, migrations.

Runs as the owner (migration) user. Idempotent. Never prints passwords.
"""

from __future__ import annotations

from psycopg import sql

from healthlake.config import db_config, secret
from healthlake.db import connect
from healthlake.db.migrate import apply_migrations

# login user role key -> group roles granted
LOGIN_USERS: dict[str, list[str]] = {
    "ingest": ["hl_ingest"],
    "dbt": ["hl_dbt"],
    "publish": ["hl_publish", "hl_dbt"],
    "api": ["hl_api_read", "hl_ops_read"],
}


def init_database() -> dict[str, object]:
    with connect("owner", autocommit=True) as conn:
        applied = apply_migrations(conn)
        created = []
        for key, groups in LOGIN_USERS.items():
            cfg = db_config(key)
            password = secret(f"HEALTHLAKE_DB_{key.upper()}_PASSWORD")
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (cfg.user,)).fetchone()
            verb = "ALTER" if exists else "CREATE"
            conn.execute(
                sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB PASSWORD {}").format(
                    sql.Identifier(cfg.user), sql.Literal(password)
                )
            )
            if not exists:
                created.append(cfg.user)
            for group in groups:
                conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(cfg.user)))
        # dbt builds release schemas as hl_dbt; it needs CREATE on the database.
        dbname = db_config("owner").dbname
        conn.execute(sql.SQL("GRANT CREATE, CONNECT ON DATABASE {} TO hl_dbt").format(sql.Identifier(dbname)))
        conn.execute("GRANT SELECT ON public.healthlake_migration TO hl_ingest, hl_ops_read")
        for group in ("hl_ingest", "hl_publish", "hl_api_read", "hl_ops_read"):
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(dbname), sql.Identifier(group))
            )
    return {"migrations_applied": applied, "users_created": created}
