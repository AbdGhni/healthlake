"""Prepare a local HealthLake installation (Windows, macOS, Linux; Docker with Linux containers).

- checks prerequisites (Python, Docker CLI, Compose v2, daemon, memory, disk, free ports);
- creates .secrets/ with random secrets (never printed) and .env from .env.example;
- --rotate-api-keys regenerates API keys only (restart api and dashboard afterwards).

Standard library only. Exit code 1 with an actionable message when a prerequisite is missing.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".secrets"
DB_SECRETS = [
    "db_owner_password",
    "db_ingest_password",
    "db_dbt_password",
    "db_publish_password",
    "db_api_password",
    "airflow_db_password",
]
API_CLIENTS = {"dashboard": ["ops", "read"], "analyst": ["read"], "operator": ["ops"]}
MIN_COMPOSE = (2, 20)
RECOMMENDED_DOCKER_MEMORY_GB = 6
RECOMMENDED_DISK_GB = 15


class Fail(SystemExit):
    def __init__(self, msg: str) -> None:
        super().__init__(f"\n[bootstrap] ERROR: {msg}\n")


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def check_prerequisites() -> list[str]:
    warnings: list[str] = []
    if sys.version_info < (3, 9):  # noqa: UP036 - helper scripts run on the host's Python, not the images'
        raise Fail("Python 3.9+ is required to run the helper scripts (the services use their own Python 3.12).")
    if shutil.which("docker") is None:
        raise Fail("Docker CLI not found. Install Docker Desktop (Windows/macOS) or Docker Engine (Linux).")
    v = run(["docker", "compose", "version", "--short"])
    if v.returncode != 0:
        raise Fail(
            "`docker compose` (Compose v2) is not available. Update Docker Desktop / install the compose plugin."
        )
    try:
        major, minor = (int(x) for x in v.stdout.strip().lstrip("v").split(".")[:2])
    except ValueError:
        major, minor = MIN_COMPOSE
    if (major, minor) < MIN_COMPOSE:
        raise Fail(f"Docker Compose {v.stdout.strip()} is too old; {MIN_COMPOSE[0]}.{MIN_COMPOSE[1]}+ is required.")
    info = run(["docker", "info", "--format", "{{json .}}"])
    if info.returncode != 0:
        raise Fail("The Docker daemon is not running. Start Docker Desktop and run bootstrap again.")
    data = json.loads(info.stdout or "{}")
    if data.get("OSType") and data["OSType"] != "linux":
        raise Fail("Docker must run Linux containers (Docker Desktop: switch to Linux containers).")
    mem_gb = data.get("MemTotal", 0) / 1024**3
    if mem_gb and mem_gb < RECOMMENDED_DOCKER_MEMORY_GB:
        warnings.append(
            f"Docker has {mem_gb:.1f} GB of memory; {RECOMMENDED_DOCKER_MEMORY_GB} GB is recommended "
            "(Docker Desktop > Settings > Resources)."
        )
    free_gb = shutil.disk_usage(ROOT).free / 1024**3
    if free_gb < RECOMMENDED_DISK_GB:
        warnings.append(
            f"{free_gb:.0f} GB free disk; about {RECOMMENDED_DISK_GB} GB are needed (images ~4 GB, "
            "extended profile data and backups)."
        )
    for port in (8000, 8080, 8501):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                warnings.append(f"port 127.0.0.1:{port} is already in use; stop the program using it before `up`.")
    return warnings


def write_secret(name: str, value: str) -> None:
    path = SECRETS / name
    path.write_text(value + "\n", encoding="utf-8")
    # Readable by the non-root container users through the bind mount; the directory itself is 0700.
    os.chmod(path, 0o644)


def token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


def generate_api_keys() -> None:
    plain, hashed = {}, []
    for key_id, scopes in API_CLIENTS.items():
        raw = f"hl_{key_id}_{token(32)}"
        plain[key_id] = raw
        hashed.append({"key_id": key_id, "sha256": hashlib.sha256(raw.encode()).hexdigest(), "scopes": sorted(scopes)})
    write_secret("api_keys.json", json.dumps(hashed, indent=2))
    write_secret("api_keys_plain.json", json.dumps(plain, indent=2))
    os.chmod(SECRETS / "api_keys_plain.json", 0o600)  # operator copy, never mounted into a container
    write_secret("dashboard_api_key", plain["dashboard"])


def generate_all() -> list[str]:
    created = []
    for name in DB_SECRETS:
        if not (SECRETS / name).exists():
            write_secret(name, token(24))
            created.append(name)
    airflow_pw = (SECRETS / "airflow_db_password").read_text().strip()
    write_secret("airflow_db_conn", f"postgresql+psycopg2://airflow:{airflow_pw}@postgres:5432/airflow")
    for name, value in (
        ("airflow_fernet_key", base64.urlsafe_b64encode(os.urandom(32)).decode()),
        ("airflow_jwt_secret", token(48)),
        ("airflow_api_secret_key", token(48)),
        ("airflow_admin_password", token(18)),
        ("api_cursor_secret", token(48)),
    ):
        if not (SECRETS / name).exists():
            write_secret(name, value)
            created.append(name)
    if not (SECRETS / "api_keys.json").exists():
        generate_api_keys()
        created.append("api keys")
    return created


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rotate-api-keys", action="store_true", help="regenerate API keys (old keys stop working)")
    ap.add_argument("--skip-docker-checks", action="store_true", help="only create secrets and .env (CI, offline)")
    a = ap.parse_args()
    print("HealthLake bootstrap - synthetic data only; not a certified healthcare platform.")
    warnings = [] if a.skip_docker_checks else check_prerequisites()
    SECRETS.mkdir(mode=0o700, exist_ok=True)
    os.chmod(SECRETS, 0o700)
    if a.rotate_api_keys:
        generate_api_keys()
        print("API keys rotated. Run: docker compose restart api dashboard")
        return
    created = generate_all()
    env = ROOT / ".env"
    if not env.exists():
        shutil.copy(ROOT / ".env.example", env)
        created.append(".env")
    print(f"Secrets directory: {SECRETS} ({'created: ' + ', '.join(created) if created else 'already complete'})")
    print("Secrets were not printed. Credentials you will need:")
    print("  Airflow  http://127.0.0.1:8080  user admin, password in .secrets/airflow_admin_password")
    print("  API      http://127.0.0.1:8000/docs  keys in .secrets/api_keys_plain.json (X-API-Key header)")
    print("  Dashboard http://127.0.0.1:8501")
    for w in warnings:
        print(f"WARNING: {w}")
    print(
        "Resources: ~4 GB of images, 6 GB of Docker memory recommended; the demo profile needs ~10 minutes "
        "for data generation and the first pipeline runs."
    )
    print("Next: docker compose build && docker compose up -d && python scripts/wait_ready.py")


if __name__ == "__main__":
    main()
