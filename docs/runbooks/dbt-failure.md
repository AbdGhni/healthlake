# Runbook: dbt failure

**Symptom**: task `dbt_build` fails. `dbt_failed` (exit 1, models errored), `dbt_unavailable` (exit 4, dbt did not
run: binary, profile or database unreachable), or the release is `built` but the gate fails on `dbt.tests`.

## Diagnose
1. Release state:
   ```sql
   SELECT release_id, schema_name, status, status_reason, params->'dbt' FROM ctl.release ORDER BY created_at DESC LIMIT 5;
   ```
2. Artifacts of that release: `artifacts/releases/<release_id>/` contains `run_results.json`, `manifest.json`,
   `release.json`, and the full dbt target with logs in `dbt-target/logs/`.
3. Failing nodes:
   ```
   python -c "import json;d=json.load(open('artifacts/releases/<release_id>/run_results.json'));[print(r['unique_id'],r['status'],(r.get('message') or '')[:200]) for r in d['results'] if r['status'] not in ('success','pass')]"
   ```
4. Compiled SQL of a failing test: `dbt-target/compiled/healthlake/...`; run it in psql against the release schema
   to see the offending rows.

## Fix
- `dbt_unavailable`: check `HEALTHLAKE_DBT_BIN` (image: `/opt/dbt-venv/bin/dbt`), the dbt secret file, database
  reachability. Retries are automatic (exit code 4).
- Model or test failure caused by data: the active release is untouched. Correct the source with a new revision.
- Model bug: fix the SQL. The release id includes a fingerprint of the dbt project, so the next run builds a new
  release id instead of reusing the failed one.
