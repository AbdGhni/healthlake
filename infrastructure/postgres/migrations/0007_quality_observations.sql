-- HealthLake 0007: the release gate also computes non-blocking observations (terminology coverage,
-- freshness, completeness), which read codings and batch metadata.
GRANT SELECT ON silver.coding TO hl_publish;
GRANT SELECT ON ctl.batch, ctl.processing TO hl_publish;
-- Operational metrics read occurrence outcomes (ids, hashes, locators; no clinical content).
GRANT USAGE ON SCHEMA bronze TO hl_ops_read;
GRANT SELECT ON bronze.resource_occurrence TO hl_ops_read;
