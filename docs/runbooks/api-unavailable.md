# Runbook: API unavailable

**Symptom**: the dashboard shows "API unavailable", or `curl http://127.0.0.1:8000/health/live` fails.

## Diagnose
1. Liveness (process up): `curl -s http://127.0.0.1:8000/health/live` -> `{"status":"ok"}`.
   No answer: `docker compose ps api` and `docker compose logs --tail 100 api`.
2. Readiness: `curl -s http://127.0.0.1:8000/health/ready`
   - `503 db_unavailable`: PostgreSQL unreachable or the API role cannot log in.
     Check `docker compose ps postgres` and the secret file mounted as `HEALTHLAKE_DB_API_PASSWORD_FILE`.
   - `503 no_active_release`: nothing published yet. Run the pipeline (see the demo or the Airflow DAGs).
3. `401` for every call: the key is wrong or `HEALTHLAKE_API_KEYS_FILE` points to another file. The API keeps
   keys in memory; restart the API after regenerating keys.
4. `410` on a pinned release or cursor: the release was purged by retention; restart paging without cursor.
5. Slow answers: `GET /metrics` (ops key), look at `healthlake_api_request_duration_seconds` by route.

## Fix
- Restart: `docker compose restart api`.
- Regenerate keys (invalidates the old ones): `python scripts/bootstrap.py --rotate-api-keys`, then
  `docker compose restart api dashboard`.
