"""Shared helpers for backup/restore (standard library only). Two runners:
- docker: the Compose project (postgres, cli containers, named volumes);
- local: a development setup (local PostgreSQL via HEALTHLAKE_BACKUP_ADMIN_DSN, data directories from
  HEALTHLAKE_*_DIR), used to verify the procedure without Docker.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_PARTS = ["lake", "artifacts", "landing"]  # work/ is rebuildable and never backed up


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)
    if res.returncode != 0:
        raise SystemExit(f"[ops] command failed ({res.returncode}): {' '.join(cmd[:6])}...\n{res.stderr[-800:]}")
    return res


TAR_IN_CLI = ["docker", "compose", "run", "--rm", "--no-deps", "-T", "--entrypoint", "tar", "cli"]


class Docker:
    name = "docker"

    def psql(self, db: str, sql: str) -> str:
        return run(
            ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "healthlake_owner", "-d", db, "-Atc", sql]
        ).stdout.strip()

    def dump(self, db: str, out: Path) -> None:
        with out.open("wb") as f:
            res = subprocess.run(
                ["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", "healthlake_owner", "-Fc", db],
                stdout=f,
                stderr=subprocess.PIPE,
                check=False,
            )
        if res.returncode != 0:
            raise SystemExit(f"[ops] pg_dump {db} failed: {res.stderr.decode()[-500:]}")

    def dump_globals(self, out: Path) -> None:
        out.write_text(
            run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dumpall",
                    "-U",
                    "healthlake_owner",
                    "--globals-only",
                ]
            ).stdout
        )

    def restore_globals(self, sql_file: Path) -> None:
        subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "healthlake_owner", "-d", "postgres"],
            stdin=sql_file.open("rb"),
            capture_output=True,
            check=False,
        )  # existing roles ok

    def restore(self, db: str, dump: Path) -> None:
        with dump.open("rb") as f:
            res = subprocess.run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "postgres",
                    "pg_restore",
                    "-U",
                    "healthlake_owner",
                    "-d",
                    db,
                    "--exit-on-error",
                ],
                stdin=f,
                capture_output=True,
                check=False,
            )
        if res.returncode != 0:
            raise SystemExit(f"[ops] pg_restore {db} failed: {res.stderr.decode()[-800:]}")

    # Archives stream through stdin/stdout instead of a bind mount: the container runs as the Airflow user, which
    # cannot write to a host directory owned by someone else (found by the first CI backup run), and streams also
    # work unchanged on Docker Desktop for Windows.
    def archive(self, part: str, out: Path) -> None:
        with out.open("wb") as f:
            res = subprocess.run(
                [*TAR_IN_CLI, "-czf", "-", "-C", "/data", part],
                stdout=f,
                stderr=subprocess.PIPE,
                check=False,
            )
        if res.returncode != 0:
            raise SystemExit(f"[ops] archive of {part} failed: {res.stderr.decode()[-500:]}")

    def unarchive(self, part: str, tgz: Path) -> None:
        with tgz.open("rb") as f:
            res = subprocess.run(
                [*TAR_IN_CLI, "-xzf", "-", "-C", "/data"],
                stdin=f,
                capture_output=True,
                check=False,
            )
        if res.returncode != 0:
            raise SystemExit(f"[ops] restore of {part} failed: {res.stderr.decode()[-500:]}")

    def reset_role_passwords(self) -> None:
        """Backups hold no password: set the login roles' passwords again from .secrets (db-init is idempotent)."""
        out = self.cli("db-init")
        if out["_exit"] != 0:
            raise SystemExit(f"[ops] db-init failed: {out}")

    def cli(self, *args: str) -> dict[str, Any]:
        res = subprocess.run(
            ["docker", "compose", "run", "--rm", "--no-deps", "cli", *args], capture_output=True, text=True, check=False
        )
        out: dict[str, Any] = json.loads(res.stdout.strip().splitlines()[-1]) if res.stdout.strip() else {}
        out["_exit"] = res.returncode
        return out


class Local:
    name = "local"

    def __init__(self) -> None:
        self.admin = os.environ["HEALTHLAKE_BACKUP_ADMIN_DSN"]
        self.dirs = {p: Path(os.environ[f"HEALTHLAKE_{p.upper()}_DIR"]) for p in DATA_PARTS}

    def _dsn(self, db: str) -> str:
        return f"{self.admin} dbname={db}"

    def psql(self, db: str, sql: str) -> str:
        return run(["psql", self._dsn(db), "-Atc", sql]).stdout.strip()

    def dump(self, db: str, out: Path) -> None:
        run(["pg_dump", "-Fc", "-f", str(out), self._dsn(db)])

    def dump_globals(self, out: Path) -> None:
        out.write_text(run(["pg_dumpall", "--globals-only", "--no-role-passwords", "-d", self.admin]).stdout)

    def restore_globals(self, sql_file: Path) -> None:
        subprocess.run(["psql", self._dsn("postgres"), "-f", str(sql_file)], capture_output=True, check=False)

    def restore(self, db: str, dump: Path) -> None:
        run(["pg_restore", "-d", self._dsn(db), "--exit-on-error", str(dump)])

    def archive(self, part: str, out: Path) -> None:
        with tarfile.open(out, "w:gz") as tar:
            tar.add(self.dirs[part], arcname=part)

    def unarchive(self, part: str, tgz: Path) -> None:
        target = self.dirs[part]
        if target.exists() and any(target.iterdir()):
            raise SystemExit(f"[ops] {target} is not empty; restore needs clean volumes")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tgz, "r:gz") as tar:
            tar.extractall(target.parent, filter="data")  # rejects absolute paths, links outside, devices

    def reset_role_passwords(self) -> None:
        out = self.cli("db-init")
        if out["_exit"] != 0:
            raise SystemExit(f"[ops] db-init failed: {out}")

    def cli(self, *args: str) -> dict[str, Any]:
        exe = os.environ.get("HEALTHLAKE_LOCAL_CLI", "healthlake")
        res = subprocess.run([exe, *args], capture_output=True, text=True, check=False)
        out: dict[str, Any] = json.loads(res.stdout.strip().splitlines()[-1]) if res.stdout.strip() else {}
        out["_exit"] = res.returncode
        return out


def runner(name: str) -> Docker | Local:
    return Docker() if name == "docker" else Local()


COUNT_SQL = (
    "SELECT json_build_object("
    "'batches', (SELECT count(*) FROM ctl.batch), 'processings', (SELECT count(*) FROM ctl.processing),"
    "'resource_versions', (SELECT count(*) FROM silver.resource_version),"
    "'occurrences', (SELECT count(*) FROM bronze.resource_occurrence),"
    "'bronze_files', (SELECT count(*) FROM bronze.file), 'issues', (SELECT count(*) FROM quality.issue),"
    "'releases_published', (SELECT count(*) FROM ctl.release WHERE status='published'),"
    "'active_release', (SELECT release_id FROM ctl.active_release))"
)


def copy_secrets_hint() -> str:
    return (
        "Secrets are NOT in the backup. Keep a separate copy of .secrets/ (same passwords are needed to "
        "use the restored database roles)."
    )
