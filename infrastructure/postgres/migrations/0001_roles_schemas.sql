-- HealthLake 0001: group roles and schemas.
-- Login users are created by healthlake.db.init (passwords from secret files) and granted these roles.
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['hl_ingest','hl_dbt','hl_publish','hl_api_read','hl_ops_read','hl_test'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
END $$;

CREATE SCHEMA IF NOT EXISTS ctl;
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS quality;
CREATE SCHEMA IF NOT EXISTS api;   -- stable views the API reads, always pointing at the active release

REVOKE ALL ON SCHEMA ctl, bronze, silver, quality, api FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
