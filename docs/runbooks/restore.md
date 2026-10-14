# Runbook: backup and restore

## Backup
```
python scripts/backup.py            # or: make backup
```
1. Pauses `healthlake_discovery` and `healthlake_ingestion`, waits for running attempts to finish.
2. Dumps roles (`pg_dumpall --globals-only --no-role-passwords`), the `healthlake` and `airflow` databases
   (`pg_dump -Fc`), archives the `lake` (Bronze), `artifacts` and `landing` volumes. `work` is not saved.
3. Re-reads the reconciliation counts; if they changed during the backup it fails (consistency check).
4. Writes `manifest.json` (SHA-256 and size of every file, counts, active release) and resumes the DAGs.

Secrets are not in the backup. Keep a separate copy of `.secrets/`.

## Restore
```
python scripts/restore.py --from backups/<timestamp> --wipe-project-volumes   # or: make restore FROM=...
```
1. Verifies every backup file against the manifest hashes (refuses a corrupted backup).
2. `docker compose down`, deletes only this project's volumes (explicit flag), starts PostgreSQL.
3. Restores roles and databases, then runs `db-init` so role passwords come from the current `.secrets/`.
4. Restores Bronze, artifacts and landing; `healthlake verify-bronze` re-hashes every Bronze object.
5. Compares reconciliation counts with the manifest; checks the active release schema exists.
6. Starts the stack, waits for readiness, and checks that the API serves the restored active release.

Any failed step stops the restore with the reason. Verified on 2026-10-14 with the `local` runner (see
docs/restore-report.md); the Docker runner uses the same steps through `docker compose`.
