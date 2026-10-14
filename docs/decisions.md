# Decisions log

- 2026-10-14: Develop and test in a Python 3.12 sandbox on PostgreSQL 16.15, because there is no Docker daemon and no PG17 there. Compose targets PG17.
- 2026-10-14: Three isolated Python environments (app, dbt, airflow). The Airflow image will carry /opt/healthlake-venv and /opt/dbt-venv.
- 2026-10-14: Synthea 4.0.0 and HL7 validator 7.0.1, both pinned by SHA-256 (config/artifact-lock.json).
- 2026-10-14: argparse instead of typer for the CLI (one dependency fewer, full control of JSON output and exit codes).
- 2026-10-14: src layout, one package `healthlake` (ADR 0001). Role model (ADR 0002).
- 2026-10-14: Synthea extensions namespace downgraded from error to warning in HL7 validation (documented).
