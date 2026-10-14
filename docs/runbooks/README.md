# Runbooks

HealthLake is a technical demonstration using synthetic data only.
It is not a certified healthcare platform and is not intended or
authorized to process real personal health data.

Conventions:
- `healthlake <cmd>` is the CLI. With Docker Compose run it as `docker compose run --rm cli <cmd>`.
- SQL: `docker compose exec postgres psql -U healthlake_owner -d healthlake`.
- Every CLI command prints one JSON line on stdout and JSON logs on stderr. Exit codes: 0 ok, 1 unexpected,
  2 contract, 3 quality, 4 transient (retry), 5 conflict.
- Never edit files in the lake (Bronze). A correction is a new source revision.

| Situation | Runbook |
|---|---|
| A batch was dropped but nothing ran | [batch-not-detected.md](batch-not-detected.md) |
| `batch_invalid` / hash or size mismatch, `bronze_integrity` | [hash-mismatch.md](hash-mismatch.md) |
| Rejected resources, `fhir.*` issues, reject rate gate | [invalid-fhir.md](invalid-fhir.md) |
| `reference_unresolved`, `reference_ambiguous`, `patient_encounter_mismatch` | [unresolved-reference.md](unresolved-reference.md) |
| `dbt_failed`, `dbt_unavailable`, dbt tests failing | [dbt-failure.md](dbt-failure.md) |
| Release not activated, `release_gate_failed` | [blocked-publication.md](blocked-publication.md) |
| A process or container died mid-run | [crash-recovery.md](crash-recovery.md) |
