# Observability

HealthLake is a technical demonstration using synthetic data only.
It is not a certified healthcare platform and is not intended or
authorized to process real personal health data.

## Structured logs
Every CLI command writes JSON lines on stderr (`healthlake.observability.log`), and its result as one JSON line on
stdout. Common fields: `timestamp` (UTC, ms), `level`, `event`, and when known `batch_id`, `processing_id`,
`attempt_id`, `release_id`. Step events carry counters (`received`, `accepted`, `rejected`, ...). Each command ends
with `command_finished` carrying `command`, `exit_code`, `duration_ms` and `error_code` on failure.
Business events are also stored in `ctl.event` (`occurred_at` uses `clock_timestamp()`, so durations between
events are real).

Never logged: secrets (messages pass through `redact()`, which masks `password=...`, URL credentials and API keys),
connection strings with passwords, resource bodies, Bundles. Only synthetic data exists in the system.

## Metrics
`healthlake metrics` prints Prometheus text; the API exposes the same collector on `GET /metrics` (phase 9) with
API latency and status codes. Values are read from the control plane and cached 30 s.

| Metric | Labels | Meaning |
|---|---|---|
| `healthlake_metrics_db_up` | | 1 if the control tables could be read |
| `healthlake_batches` | status | registered batches |
| `healthlake_processings` | source_id, status | processings |
| `healthlake_attempts` | status | attempts (succeeded, failed, blocked, running) |
| `healthlake_resources` | source_id, resource_type (7 + other), outcome | resource occurrences |
| `healthlake_quality_issues` | check_id, severity | quarantine rows |
| `healthlake_pipeline_last_duration_seconds` | source_id | last succeeded attempt, start to finish |
| `healthlake_last_success_timestamp_seconds` | source_id | freshness of ingestion |
| `healthlake_active_release_age_seconds` | | age of the published dataset |
| `healthlake_active_release_activated_timestamp_seconds` | | activation time |
| `healthlake_releases` | status | releases |

Label cardinality is bounded (no batch, processing, attempt, release, patient or code as label).

Sample from the demo profile in the sandbox (2026-10-14):
```
healthlake_attempts{status="succeeded"} 3.0
healthlake_resources{outcome="accepted",resource_type="Observation",source_id="horizon-central"} 31421.0
healthlake_resources{outcome="accepted",resource_type="Observation",source_id="horizon-nord"} 23787.0
healthlake_resources{outcome="accepted",resource_type="Observation",source_id="horizon-sud"} 30275.0
healthlake_pipeline_last_duration_seconds{source_id="horizon-central"} 111.776576
healthlake_pipeline_last_duration_seconds{source_id="horizon-nord"} 42.566367
healthlake_pipeline_last_duration_seconds{source_id="horizon-sud"} 53.547838
healthlake_releases{status="published"} 1.0
```

## Quality signals
- Processing gate and release gate results: `quality.check_result` (see docs/quality-catalog.md).
- Quarantine: `quality.issue`. Attempt summary: `healthlake inspect --attempt-id ...`; report files:
  `artifacts/reports/<attempt_id>.json`.
- Bronze integrity: `healthlake verify-bronze`.

## Housekeeping
`healthlake gc-work --older-than-hours 24` deletes work files of loaded or blocked processings (demo profile:
about 940 MB of work files). Steps decide idempotence from the database first, so a replay after cleanup does not
redo any work (tested).
