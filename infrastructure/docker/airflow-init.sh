#!/bin/bash
# One-shot Airflow initialisation: migrate metadata DB, create/refresh the admin user, create pools.
set -euo pipefail
airflow db migrate
pw="$(cat /run/secrets/airflow_admin_password)"
if airflow users list --output json 2>/dev/null | grep -q '"username": "admin"'; then
  airflow users reset-password --username admin --password "$pw" > /dev/null
else
  airflow users create --username admin --password "$pw" --firstname HealthLake --lastname Admin \
    --role Admin --email admin@healthlake.invalid > /dev/null
fi
airflow pools set healthlake_ingestion 1 "HealthLake ingestion (one batch at a time)"
airflow pools set healthlake_publication 1 "HealthLake release publication"
echo "airflow-init done"
