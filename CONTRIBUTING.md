# Contributing

HealthLake is a technical demonstration using synthetic data only. Contributions must never include real personal
health data, real identifiers or credentials.

## Development setup
```
uv venv --python 3.12 .venvs/app && uv pip install --python .venvs/app/bin/python --require-hashes -r requirements/dev.lock
uv pip install --python .venvs/app/bin/python --no-deps -e .
uv venv --python 3.12 .venvs/dbt && uv pip install --python .venvs/dbt/bin/python --require-hashes -r requirements/dbt.lock
```
Tests need a disposable PostgreSQL (`HEALTHLAKE_TEST_ADMIN_DSN`, superuser) and `HEALTHLAKE_DBT_BIN` for release
tests. Airflow and dashboard tests run in their own virtualenvs (see the CI workflow).

## Rules
- `ruff check`, `ruff format --check`, `mypy` (strict) and the test suites must pass.
- Dependencies change only through `requirements/*.in` + `uv pip compile --generate-hashes`.
- A new quality check must be added to `config/quality-catalog.json` (a test enforces it), then
  `python scripts/gen_quality_catalog.py`.
- API changes: `python scripts/export_openapi.py` (a test enforces an up-to-date contract).
- Never edit an applied migration; add a new numbered one.
