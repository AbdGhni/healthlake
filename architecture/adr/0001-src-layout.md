# ADR 0001: one Python package with a src layout

Status: accepted (2026-10-14)

The prompt lists top-level folders `ingestion/`, `validation/`, `normalization/`, `quality/`, `pipelines/`.
Top-level Python packages with generic names collide easily and make imports ambiguous.
HealthLake ships one installable package, `healthlake`, under `src/`, with those areas as subpackages
(`healthlake.ingestion`, `healthlake.validation`, ...). Non-Python assets keep their top-level folders
(`airflow/dags`, `dbt`, `dashboards`, `infrastructure`).

Consequence: one console entry point (`healthlake`), one import root, clean installs with `pip install .`.
