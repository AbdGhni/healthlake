-- HealthLake 0006: snapshot rebuild and release bookkeeping privileges.
GRANT DELETE ON silver.snapshot_member, silver.snapshot_reference TO hl_ingest;
GRANT SELECT ON ctl.release_processing TO hl_api_read, hl_ops_read;
GRANT SELECT ON quality.check_result, quality.issue TO hl_ops_read;
GRANT SELECT ON ctl.source TO hl_api_read, hl_ops_read;
-- The release gate runs as the publish role: it reads the candidate schema (owned by hl_dbt)
-- and records its results.
GRANT INSERT, UPDATE ON quality.check_result TO hl_publish;
GRANT SELECT ON silver.snapshot_member, ctl.release_processing TO hl_publish;
