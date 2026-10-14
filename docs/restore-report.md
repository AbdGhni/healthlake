# Backup and restore report

Date: 2026-10-14. Environment: build sandbox, **local runner** (PostgreSQL 16.15, directories), because no Docker
daemon is available there. The Docker runner (`--runner docker`, default) runs the same steps through
`docker compose`; it is **not verified** in this environment.

## Procedure run
1. Source: database `healthlake_demo2` after the five demo scenarios (test profile).
2. `python scripts/backup.py --runner local --db healthlake_demo2 --out /home/claude/backups`
3. `python scripts/restore.py --from <backup> --runner local --db healthlake_restored` into a new database and new,
   empty data directories, with the API restarted on the restored database.

## Results (copied from the command output)
| Check | Result |
|---|---|
| backup files vs manifest SHA-256 | verified |
| role dump contains password verifiers | no (0 `SCRAM` entries; `--no-role-passwords`) |
| role passwords after restore | set again from `.secrets` by `db-init` |
| Bronze objects re-hashed (`verify-bronze`) | 19 objects, 0 missing, 0 corrupted |
| reconciliation counts | identical: 7 batches, 7 processings, 2 931 resource versions, 3 716 occurrences, 19 Bronze files, 5 issues, 3 published releases |
| active release | `62411a0fa0d3...` restored and served by the API (`/v1/summary`, 10 patients) |
| corrupted backup (1 byte appended to lake.tgz) | refused: "lake.tgz does not match the manifest hash" |
| restore into an existing database | refused: "restore needs a clean target" |

## Not verified here
- `--runner docker`: pausing DAGs through the Airflow CLI, `docker volume rm` of project volumes, the Airflow
  metadata restore. Command to verify on a Docker machine:
  `python scripts/backup.py && python scripts/restore.py --from backups/<timestamp> --wipe-project-volumes`
  (also run by the CI `e2e` job).
