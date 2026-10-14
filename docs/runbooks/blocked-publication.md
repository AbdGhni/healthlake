# Runbook: publication blocked

**Symptom**: `quality_gate` fails with `release_gate_failed` (exit 3) or `publish` with `release_not_publishable` /
`release_incomplete`. The dashboard keeps showing the previous release: this is the intended behaviour.

## Diagnose
```sql
SELECT check_id, status, observed, threshold, details FROM quality.check_result
WHERE scope = 'release' AND scope_id = '<release_id>' ORDER BY check_id;
SELECT release_id, activated_at FROM ctl.active_release;
```
Blocking checks: `dbt.tests`, `dbt.models`, `release.schema_complete`, `release.snapshot_dangling_references`,
`release.gold_reconciles_snapshot`, `release.processings_passed`. Observations with status `warn`
(terminology coverage, freshness) never block.

## Fix
Follow the failing check: dbt (see dbt-failure.md), reconciliation (compare `params->'snapshot'` with Gold
counts), schema (rerun `healthlake dbt-build --release-id ...`).

## Rollback to an earlier release
Any release with status `published` (not `purged`) can be re-activated atomically:
```
healthlake publish --release-id <older published release_id>
```

## Demonstration only
`HEALTHLAKE_INJECT_GATE_FAILURE=1` makes a dbt test fail on purpose (scenario `blocked-publication`). It changes
the release id and cannot affect a normal release.
