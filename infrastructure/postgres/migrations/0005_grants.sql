-- HealthLake 0005: privileges. Owner role (migrations) owns everything; others get the minimum.
GRANT USAGE ON SCHEMA ctl, bronze, silver, quality TO hl_ingest;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ctl, bronze, silver, quality TO hl_ingest;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ctl, quality TO hl_ingest;

GRANT USAGE ON SCHEMA ctl, silver, quality TO hl_dbt;
GRANT SELECT ON ALL TABLES IN SCHEMA silver, quality TO hl_dbt;
GRANT SELECT ON ctl.release, ctl.release_processing, ctl.processing, ctl.batch, ctl.source TO hl_dbt;

GRANT USAGE ON SCHEMA ctl, quality, api TO hl_publish;
GRANT SELECT, UPDATE ON ctl.release, ctl.active_release TO hl_publish;
GRANT INSERT ON ctl.event TO hl_publish;
GRANT USAGE ON SEQUENCE ctl.event_event_id_seq TO hl_publish;
GRANT SELECT ON quality.check_result TO hl_publish;

-- API reads control metadata it needs plus released schemas (granted per release at publish time).
GRANT USAGE ON SCHEMA ctl, api TO hl_api_read;
GRANT SELECT ON ctl.release, ctl.active_release TO hl_api_read;
GRANT USAGE ON SCHEMA ctl, quality TO hl_ops_read;
GRANT SELECT ON ctl.attempt, ctl.processing, ctl.batch, ctl.event, ctl.release, quality.check_result TO hl_ops_read;
