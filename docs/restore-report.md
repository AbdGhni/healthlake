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

## Docker runner (CI, 2026-10-15)
`python3 scripts/backup.py`, then `python3 scripts/restore.py --from backups/<timestamp> --wipe-project-volumes`
in the CI `e2e` job, on the stack after the five demo scenarios ([run](https://github.com/AbdGhni/healthlake/actions/runs/38810331362)):
- backup files verified against the manifest hashes;
- role passwords set again from `.secrets`;
- Bronze re-hashed: 18 objects, 0 missing, 0 corrupted;
- reconciliation counts identical to the manifest: 6 batches, 2 931 resource versions, 3 716 occurrences,
  4 published releases;
- API smoke test on the restored active release.
