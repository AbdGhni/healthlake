-- HealthLake 0009: fresh planner statistics for the snapshot tables before dbt reads them.
-- Found by the demo scenarios on the demo profile: the second release was planned while autovacuum had not yet
-- analyzed the new snapshot rows, and two dbt models ran for more than 13 minutes (nested loops on stale
-- estimates); with fresh statistics the same query plans as hash joins. ANALYZE needs table ownership, so the
-- ingestion role gets this one narrow SECURITY DEFINER function instead of owning the tables.
CREATE FUNCTION silver.analyze_snapshot() RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  ANALYZE silver.snapshot_member;
  ANALYZE silver.snapshot_reference;
END
$$;
REVOKE ALL ON FUNCTION silver.analyze_snapshot() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION silver.analyze_snapshot() TO hl_ingest;
