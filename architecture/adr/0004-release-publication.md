# ADR 0004: versioned Gold releases and atomic publication

Status: accepted (2026-10-14)

## Decision
- A release is identified by `release_id = sha256(sorted loaded processing ids, code version, dbt project
  fingerprint + build options)`. The snapshot id equals the release id.
- `build-release` writes a deterministic snapshot (`silver.snapshot_member`: per identity, the version from the
  highest `source_revision`; ties broken by processing id), then runs `dbt build` into a new schema
  `release_<first 16 hex of release_id>` with role `hl_dbt`. Gold is fully rebuilt for every release.
- `quality-gate` runs as the publish role and records 6 checks in `quality.check_result` (scope `release`):
  dbt tests, dbt models, schema completeness, dangling snapshot references, Gold vs snapshot reconciliation,
  every included processing passed its own gate.
- `publish` (one transaction): lock release and active pointer, require `gate_passed`, re-check schema
  completeness, grant `SELECT` on the 15 Gold marts (not staging views) to `hl_api_read`, mark published,
  move `ctl.active_release`. Retention keeps the active release plus N other published ones
  (`HEALTHLAKE_RELEASE_RETENTION`, default 3); older schemas are dropped and marked `purged`.

## Consequences
- A failed build or gate never touches the active release (tested).
- Fixing a dbt model changes the fingerprint, hence the release id: a failed release is never "repaired in place".
- Consumers resolve the schema name from `ctl.release`, never from user input.
- Fault injection for demonstrations (`HEALTHLAKE_INJECT_GATE_FAILURE=1`) is part of the build options,
  so it produces a distinct release id and cannot affect a normal release.
