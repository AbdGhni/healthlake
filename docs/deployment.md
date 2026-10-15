# Deployment (local, Docker Compose)

> HealthLake is a technical demonstration using synthetic data only.
> It is not a certified healthcare platform and is not intended or
> authorized to process real personal health data.

## Requirements
Docker Desktop (Windows/macOS, Linux containers) or Docker Engine with Compose v2.20+; 6 GB of Docker memory
recommended; ~15 GB free disk; Python 3.9+ on the host for the helper scripts (standard library only); Internet
access for the first build (images, Python wheels, Temurin JRE, Synthea and validator jars, FHIR packages).
After the build, the pipeline, validation and demo run without any external terminology server.

## Steps
```
python scripts/bootstrap.py        # checks prerequisites, creates .secrets/ and .env, prints where credentials are
docker compose build               # 3 images: platform (Airflow+HealthLake+dbt+Java), api, dashboard
docker compose up -d
python scripts/wait_ready.py       # waits for db-init, airflow-init and health of every service
python scripts/demo.py --scenario happy-path
```
Make equivalents: `make bootstrap build up demo`. `make down` keeps data; `make reset` deletes this project's
volumes after typing `yes`. These are several steps on purpose: HealthLake does not claim a one-command setup.

## Services
| Service | Image | Role | Port (host) | Networks |
|---|---|---|---|---|
| postgres | postgres:17.11-bookworm (digest) | healthlake + airflow databases | not exposed | data_net |
| db-init | platform | migrations, login roles (one-shot) | - | data_net |
| airflow-init | platform | metadata migration, admin user, pools (one-shot) | - | data_net |
| airflow-api-server | platform | Airflow UI/API, execution API | 127.0.0.1:8080 | data_net |
| airflow-scheduler | platform | LocalExecutor, runs the CLI tasks | - | data_net |
| airflow-dag-processor | platform | parses DAGs | - | data_net |
| api | api | FastAPI, read-only | 127.0.0.1:8000 | data_net, app_net |
| dashboard | dashboard | Streamlit, talks to the API only | 127.0.0.1:8501 | app_net |
| cli (profile tools) | platform | `docker compose run --rm cli <command>` | - | data_net |
| synthea (profile tools) | platform | `docker compose run --rm synthea --profile demo --revision 1` | - | data_net |

No Redis, no Celery, no triggerer (no deferrable operator), no Docker socket mounted.

Volumes: `pg_data`, `landing`, `lake`, `work`, `artifacts`, `airflow_logs`. Secrets: files in `.secrets/`
mounted at `/run/secrets/*`, read through `*_FILE` variables or Airflow `*_CMD` options.

## Images
- **platform**: `apache/airflow:3.3.2-python3.12` (digest, Debian bookworm) + Temurin JRE 21.0.12.1 (SHA-256 per
  architecture) + `validator_cli.jar` 7.0.1 and Synthea 4.0.0 (`ADD --checksum`) + `/opt/healthlake-venv`
  (app.lock) and `/opt/dbt-venv` (dbt.lock), both installed with `--require-hashes` and `pip check`. The build
  runs the validator once so FHIR packages are cached for offline validation. Airflow itself never imports
  HealthLake or dbt (separate virtualenvs; tasks call `/usr/local/bin/healthlake`).
- **api**: `python:3.12.15-slim-bookworm` (digest) + app.lock; UID 10001; read-only root FS; caps dropped.
- **dashboard**: same base + dashboard.lock; UID 10001; read-only root FS; caps dropped.

## Verification status (2026-10-15)
| Item | Status |
|---|---|
| `docker compose config` (with and without profile tools) | verified |
| image digests, Temurin checksum, jar checksums | verified (pinned; checked at build time) |
| `docker compose build` (3 images), Trivy scan of the API image (HIGH/CRITICAL, fixed) | **verified in CI** |
| `docker compose up`, all health checks, `db-init` and `airflow-init` | **verified in CI** |
| Airflow 3.3.2 in containers: the five demo scenarios through the Airflow REST API | **verified in CI** |
| backup and restore with the Docker runner (`--wipe-project-volumes`), API smoke test after restore | **verified in CI** |
| app test suite on PostgreSQL 17.11 | **verified in CI** |
| Docker Desktop on Windows, arm64 images | not verified |

CI evidence: [run 38810331362](https://github.com/AbdGhni/healthlake/actions/runs/38810331362) (GitHub Actions, `ubuntu-24.04`). The first CI runs found five
defects that the sandbox could not reveal, all fixed: image file permissions for the Airflow user, Airflow
`*_CMD` secrets passed with a trailing newline, backup archives written through a bind mount the container could
not write to, a missing password reset in the Docker restore path, and a backup that froze in-flight runs by
pausing the ingestion DAG (see docs/decisions.md).
