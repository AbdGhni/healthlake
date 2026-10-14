# Runbook: batch not detected

**Symptom**: a batch directory exists under `landing/<source_id>/` but no `healthlake_ingestion` run appears.

## Diagnose
1. Is the batch finalized? Discovery only reads `landing/<source_id>/<dir>/manifest.json`. Directories starting
   with `.` (for example `.tmp-rev-000003`) are in-progress writes and are ignored on purpose.
2. Run discovery by hand and read the per-batch result:
   ```
   healthlake discover
   ```
   - `"registered": true|false` with a `batch_id`: the batch is known.
   - `"error_code": "manifest_invalid"`: see the message (synthetic must be true, paths sorted, relative, no `..`).
   - `"error_code": "unknown_source"`: the parent directory is not a source in `config/sources.json`.
   - `"error_code": "revision_conflict"`: the revision already exists with other content (exit code 5).
3. Is it pending? `pending_batch_ids` lists batches without a loaded or blocked processing.
4. In Airflow, check that `healthlake_discovery` is unpaused and its last runs succeeded; look for the
   `trigger_ingestion` mapped task of the latest run. Ingestion run ids are `batch__<batch_id>`.

## Fix
- Incomplete write: let the producer finish; the writer renames the directory only after `manifest.json` is written.
- Invalid manifest: produce a corrected batch as a new revision directory (`rev-<N+1>`).
- Revision conflict: never overwrite a revision. Publish the corrected content as a new revision.
- Paused DAG: unpause `healthlake_discovery` and `healthlake_ingestion` in the Airflow UI.

## Verify
`healthlake discover` lists the batch id in `pending_batch_ids`, and an ingestion run `batch__<batch_id>` appears
within 5 minutes.
