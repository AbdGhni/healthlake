-- HealthLake 0008: snapshot build at the extended profile (1.8 M members).
-- The foreign key snapshot_member -> resource_version cost ~95 s of row-by-row checks per build. Members are
-- produced by a join with silver.resource_version in the same statement, and resource versions are never deleted,
-- so the key cannot be violated by the only writer; the build still checks dangling references and counts.
ALTER TABLE silver.snapshot_member DROP CONSTRAINT IF EXISTS snapshot_member_resource_version_id_fkey;
