# Runbook: hash or size mismatch

**Symptom**: `healthlake verify` (task `verify`) fails with exit code 2 and `"error_code": "batch_invalid"`,
or `healthlake verify-bronze` exits 3 with `bronze_integrity`.

## Landing batch (`batch_invalid`)
1. Read the problems: the JSON output lists `problems` (hash mismatch, size mismatch, undeclared or missing file,
   symbolic link). The same text is stored in `ctl.batch.status_reason`:
   ```sql
   SELECT source_id, source_revision, status, status_reason FROM ctl.batch WHERE batch_id = '<batch_id>';
   ```
2. The batch stays `invalid`; nothing was archived. The file in landing is not what the producer declared.
3. Fix at the producer: write a **new revision** with a correct manifest. Do not edit the manifest of an existing
   revision (its `batch_id` is the hash of the manifest; a different manifest for the same revision is a conflict).

## Bronze store (`bronze_integrity`)
1. `healthlake verify-bronze` re-hashes every registered object. Output fields:
   `missing` (registered, no file), `corrupted` (file content differs from its hash), `unregistered` (file without
   registry row, harmless leftovers of an interrupted archive).
2. Missing or corrupted objects mean the lake volume was altered outside HealthLake (the store never overwrites).
3. Restore the affected objects from the latest backup (`docs/runbooks/restore.md`, phase 11); objects are
   content-addressed, so a restored file is accepted only if its SHA-256 matches.
4. Re-run `healthlake verify-bronze` until it exits 0.

HealthLake's immutability is application-level (exclusive create, no overwrite, verification on read). It is not
WORM storage and does not protect against an administrator with filesystem access.
