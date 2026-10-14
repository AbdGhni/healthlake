#!/bin/bash
# Runs once, on an empty data directory (official postgres entrypoint). Creates the Airflow metadata role and DB.
set -euo pipefail
pw="$(cat /run/secrets/airflow_db_password)"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=pw="$pw" <<'SQL'
SELECT format('CREATE ROLE airflow LOGIN PASSWORD %L', :'pw') \gexec
CREATE DATABASE airflow OWNER airflow;
REVOKE ALL ON DATABASE airflow FROM PUBLIC;
SQL
