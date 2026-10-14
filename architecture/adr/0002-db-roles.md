# ADR 0002: PostgreSQL roles

Status: accepted (2026-10-14)

Group roles (NOLOGIN) carry privileges; login users are created by `healthlake db-init` from secret files.

| Login user | Groups | Purpose |
|---|---|---|
| healthlake_owner | superuser in the container | migrations only |
| healthlake_ingest | hl_ingest | registry, Bronze, Silver, quality writes |
| healthlake_dbt | hl_dbt | reads Silver, creates `release_*` schemas (objects owned by hl_dbt) |
| healthlake_publish | hl_publish, hl_dbt | grants read on a built release, flips `ctl.active_release` |
| healthlake_api | hl_api_read, hl_ops_read | read-only: active release views, control and quality metadata |
| airflow | own database | Airflow metadata only |

The API user cannot read Bronze or Silver (tested). The ingest user cannot create schemas (tested).
Role names are cluster-wide, so tests that create several databases reuse the same login users.
