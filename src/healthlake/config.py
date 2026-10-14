"""Runtime configuration from environment variables.

Secrets are read from files (VAR_FILE) when present, else from VAR. No secret has a default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    pass


def secret(name: str, required: bool = True) -> str | None:
    path = os.environ.get(f"{name}_FILE")
    if path:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"cannot read secret file for {name}: {exc.strerror}") from None
        if not value:
            raise ConfigError(f"secret file for {name} is empty")
        return value
    env_value = os.environ.get(name)
    if env_value:
        return env_value
    if required:
        raise ConfigError(f"missing secret {name} (set {name}_FILE)")
    return None


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise ConfigError(f"missing setting {name}")
    return value


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str | None

    def conninfo(self) -> str:
        parts = {"host": self.host, "port": str(self.port), "dbname": self.dbname, "user": self.user}
        if self.password:
            parts["password"] = self.password
        return " ".join(f"{k}={_quote(v)}" for k, v in parts.items())


def _quote(v: str) -> str:
    return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"


def db_config(role: str) -> DbConfig:
    """role is one of owner, ingest, dbt, publish, api, ops, test."""
    key = role.upper()
    return DbConfig(
        host=env("HEALTHLAKE_DB_HOST", "postgres"),
        port=int(env("HEALTHLAKE_DB_PORT", "5432")),
        dbname=env("HEALTHLAKE_DB_NAME", "healthlake"),
        user=env(f"HEALTHLAKE_DB_{key}_USER", f"healthlake_{role}"),
        password=secret(f"HEALTHLAKE_DB_{key}_PASSWORD", required=False),
    )


@dataclass(frozen=True)
class Paths:
    landing: Path
    lake: Path
    work: Path
    artifacts: Path


def paths() -> Paths:
    return Paths(
        landing=Path(env("HEALTHLAKE_LANDING_DIR", "/data/landing")),
        lake=Path(env("HEALTHLAKE_LAKE_DIR", "/data/lake")),
        work=Path(env("HEALTHLAKE_WORK_DIR", "/data/work")),
        artifacts=Path(env("HEALTHLAKE_ARTIFACTS_DIR", "/data/artifacts")),
    )
