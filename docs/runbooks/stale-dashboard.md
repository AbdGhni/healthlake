# Runbook: dashboard shows old data

**Symptom**: the dashboard header shows an old "Published" time, or numbers do not include a recent batch.

The dashboard only shows the **active published release**. It never reads the database. By design a failed or
blocked run keeps the previous release active, so "old" data is usually the expected safe behaviour.

## Diagnose
1. Header of any page: `Release <id>`, `Published <UTC time> · <age> ago`, API state.
2. Pipeline Operations page: latest attempts (blocked/failed with `error_code`) and the releases list.
3. Is a newer release waiting or blocked?
   ```sql
   SELECT left(release_id,12), status, status_reason, created_at, published_at FROM ctl.release
   ORDER BY created_at DESC LIMIT 5;
   ```
   - `gate_failed` / `failed`: see blocked-publication.md / dbt-failure.md.
   - no new release: the batch was blocked (invalid-fhir.md) or not detected (batch-not-detected.md).
4. Caching: release metadata is cached 20 s and data 10 min per (endpoint, filters, release id). A new
   publication is picked up within 20 s; reload the page (browser refresh) to re-pin the page on it.

## Fix
Follow the runbook of the failing stage. Do not force a publication: `healthlake publish` only accepts releases
that passed the gate.
