# HealthLake - convenience targets. Every target calls a documented command; the Python helper scripts work on
# Windows without make (see README).
PY ?= python
COMPOSE ?= docker compose

.PHONY: bootstrap build up demo test test-airflow test-dashboard lint down reset backup restore

bootstrap:          ## check prerequisites, create .secrets and .env
	$(PY) scripts/bootstrap.py

build:              ## build the three images
	$(COMPOSE) build

up:                 ## start the stack and wait until it is ready
	$(COMPOSE) up -d
	$(PY) scripts/wait_ready.py

demo:               ## run all demonstration scenarios on the running stack
	$(PY) scripts/demo.py --scenario all

lint:
	ruff check src tests scripts airflow dashboards
	ruff format --check src tests scripts airflow dashboards
	mypy
	mypy --strict --ignore-missing-imports scripts/*.py

test:               ## app test suite (needs HEALTHLAKE_TEST_ADMIN_DSN, HEALTHLAKE_DBT_BIN for dbt tests)
	pytest -q

test-airflow:       ## DAG tests, in the Airflow virtualenv
	.venvs/airflow/bin/python -m pytest -q tests/airflow

test-dashboard:     ## dashboard tests, in the dashboard virtualenv
	.venvs/dashboard/bin/python -m pytest -q tests/dashboard

down:               ## stop containers, KEEP data volumes
	$(COMPOSE) down

reset:              ## stop containers AND delete this project's volumes (asks for confirmation)
	@echo "This deletes all HealthLake data volumes (database, lake, artifacts). Type 'yes' to continue:"; \
	read answer; [ "$$answer" = "yes" ] && $(COMPOSE) down --volumes || echo "aborted"

backup:             ## consistent backup into backups/<timestamp>/
	$(PY) scripts/backup.py

restore:            ## make restore FROM=backups/<timestamp>
	$(PY) scripts/restore.py --from $(FROM) --wipe-project-volumes
