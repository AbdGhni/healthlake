# Runbook: recovery after a crash

Every step is idempotent and re-runnable. The safe action after any crash is to **re-run the same step** (or clear
the failed Airflow task / re-trigger the run `batch__<batch_id>`). Tested crash points (tests/recovery,
tests/integration/test_release.py):

| Crash point | State left | What the re-run does |
|---|---|---|
| after archive, before status | objects in Bronze, processing `pending` | re-hashes, no new object, marks `archived` |
| during Silver load | transaction rolled back, processing `normalized` | loads once |
| after Silver commit, before return (kill -9) | processing `loaded`, attempt `running` | load returns `idempotent`; a new attempt succeeds |
| during dbt | release `building` | rebuilds the snapshot and Gold |
| after gate, before publish | release `gate_passed` | gate `idempotent`, publish activates |
| after publish commit, before return (kill -9) | release `published` and active | publish returns `idempotent` |
| during final report | attempt closed, no report file | report written |
| two concurrent attempts of a batch | one holds the processing lock | the other exits 4 (`processing_locked`) and is retried |

## Orphan attempts
An attempt stays `running` if its process was killed. It is informational; close it with:
```
healthlake finish --attempt-id <attempt_id>
```
The status is derived from the processing (`succeeded` if loaded, `blocked`, or `failed`).

## Interrupted work files
Work files are written to unique temporary names and renamed; a `<step>.done.json` marker means the step output is
complete. Leftover `*.tmp` files in `work/<processing_id>/` are safe to delete.
