# Decisions log

- 2026-10-14: Develop and test in a Python 3.12 sandbox on PostgreSQL 16.15, because there is no Docker daemon and no PG17 there. Compose targets PG17.
- 2026-10-14: Three isolated Python environments (app, dbt, airflow). The Airflow image will carry /opt/healthlake-venv and /opt/dbt-venv.
- 2026-10-14: Synthea 4.0.0 and HL7 validator 7.0.1, both pinned by SHA-256 (config/artifact-lock.json).
- 2026-10-14: argparse instead of typer for the CLI (one dependency fewer, full control of JSON output and exit codes).
- 2026-10-14: src layout, one package `healthlake` (ADR 0001). Role model (ADR 0002).
- 2026-10-14: Validation in two tiers: structural on every resource (blocking), HL7 validator on a deterministic sample (audit) (ADR 0003).
- 2026-10-14: Identifier references resolve only inside the source namespace (Synthea reuses NPI sequences across populations; cross-source resolution would merge establishments).
- 2026-10-14: CLI steps run on an autocommit connection; each step commits explicit transactions so quarantine and blocked status survive the raised error. A PostgreSQL advisory lock per processing serializes concurrent attempts (the loser gets exit code 4, retryable).
- 2026-10-14: Work files are NDJSON written to a unique temp name then renamed; a `<step>.done.json` marker makes steps re-runnable after a crash.
- 2026-10-14: resource_version_id excludes the revision, so unchanged content across revisions is stored once; `silver.processing_resource.source_revision` carries the business order used by snapshots.
- 2026-10-14: Medication codes for `medicationReference` are resolved from Medication resources of the same processing or from contained resources; Medication from earlier batches is not looked up (documented limit).
- 2026-10-14: Release id includes a fingerprint of the dbt project and build options (ADR 0004).
- 2026-10-14: The release gate runs as the publish role (it must read the candidate schema owned by hl_dbt).
- 2026-10-14: The API role reads only the 15 Gold marts; staging views (which select from Silver) are not granted.
