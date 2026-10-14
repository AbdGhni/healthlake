# Compatibility (verified 2026-10-14)

Python dependencies were resolved with `uv pip compile --python-version 3.12 --generate-hashes`, installed with `--require-hashes`, and checked with `uv pip check`.

| Component | Version | How it was checked |
|---|---|---|
| Python | 3.12.3 | sandbox interpreter |
| pydantic | 2.14.1 | app.lock, pip check OK |
| SQLAlchemy | 2.1.4 | app.lock |
| psycopg | 3.3.6 (binary) | app.lock, integration tests |
| FastAPI / uvicorn | 0.143.1 / 0.54.0 | app.lock |
| polars / pyarrow | 2.0.0 / 26.0.0 | app.lock |
| dbt-core / dbt-postgres | 1.12.6 / 1.11.0 | dbt.lock resolves, pip check OK, separate venv |
| Streamlit | 1.65.0 | dashboard.lock |
| Apache Airflow | 3.3.2 | official `constraints-3.3.2/constraints-3.12.txt`, pip check OK, separate venv |
| PostgreSQL | 16.15 tested; 17 targeted in compose | PG17 not verified (no server in the sandbox) |
| Synthea | 4.0.0 jar, SHA-256 pinned | ran with fixed seeds; two runs gave byte-identical bundles |
| HL7 FHIR validator | 7.0.1 jar, SHA-256 pinned | validated a valid and an invalid Patient with `-version 4.0.1 -tx n/a` |
| Java | 21.0.12 tested; 17 targeted in image | Java 17 not verified here |

## Observations
- Synthea 4.0.0 fails to write files whose patient name contains non-ASCII characters unless the JVM runs with
  `-Dsun.jnu.encoding=UTF-8` and a UTF-8 locale. HealthLake also sets `exporter.use_uuid_filenames=true`.
- The HL7 validator reports Synthea's own extensions (`http://synthetichealth.github.io/synthea/...`) as errors because
  their definitions are not published. HealthLake downgrades exactly that namespace to a warning (documented allowlist).
- The validator needs about 25 s to load packages and about 750 MB of memory. On first run it downloads
  `hl7.fhir.r4.core#4.0.1` and terminology packages; afterwards it runs offline from `~/.fhir/packages`.
- dbt Core 1.12 prints a notice about dbt v2. The project stays on the pinned v1.

## Sources consulted
- PyPI metadata via uv resolution (2026-10-14).
- Airflow constraints: https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
- Synthea CLI: `java -jar synthea-with-dependencies.jar -h` (v4.0.0).
- HL7 validator CLI: `java -jar validator_cli.jar -help` (7.0.1).
- Maven Central metadata for org.hl7.fhir.validation (latest 7.0.1).
