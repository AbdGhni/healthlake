# Performance report

> HealthLake is a technical demonstration using synthetic data only.
> It is not a certified healthcare platform and is not intended or
> authorized to process real personal health data.

Every number below comes from a JSON file in this folder, written by the measurement scripts. The full tables
are generated into [results.md](results.md) by `scripts/perf_report.py`. Measured on 2026-10-15.

## Machine and conditions
| Item | Value |
|---|---|
| CPU | 2 vCPU, Intel Xeon @ 2.80 GHz (shared cloud VM) |
| Memory | 7 GB in the VM; a 5.84 GiB cgroup limit applies to every process of the run, PostgreSQL included |
| Disk | virtual disk, local |
| PostgreSQL | 16.15, `shared_buffers=256MB`, other settings default (`work_mem=4MB`) |
| Python / Java | 3.12.3 / Temurin 21 (HL7 validator `-Xmx2g`) |
| Runner | local CLI, the same commands Airflow calls; **no Docker** (no daemon in the sandbox) |
| API | uvicorn, 2 workers; load clients on the **same VM** |

These are the numbers of a small VM, not of a server. They show orders of magnitude, how the steps scale and where
the time goes. They are not a benchmark to compare with other systems.

## Protocol
- **Generation** (`healthlake generate`) runs Synthea and derives the CSV/JSON sources. It is timed separately
  from the pipeline: it is test-data production, not part of HealthLake's processing.
- **Pipeline**: `scripts/perf_pipeline.py` runs `discover`, `ingest` for each batch, then `build-snapshot`,
  `dbt-build`, `dbt-docs`, `quality-gate` and `publish`. Each command runs in a fresh process, measured by
  `scripts/measure.py` (wall time; peak RSS of the largest process). Per-step durations come from `ctl.event`
  timestamps.
- Every run uses a **fresh database and fresh lake/work directories**.
  - **Cold**: PostgreSQL restarted and the OS page cache dropped before the run.
  - **Warm**: the same run repeated right after.
- **Extended** runs use `--gc-work`, which deletes work files after each load, to fit the disk budget.
- **API**: `scripts/perf_api.py` runs 5 client threads. Each client loops over 9 endpoints in its own random
  order: 5 aggregate endpoints and 4 paginated lists. Latency is client side and includes HTTP.
  - Cold: PostgreSQL restarted, page cache dropped, API restarted, then 2 rounds.
  - Warm: 40 rounds right after.
- Profiles: **demo** is 100 patients per source and **extended** 1 000, each over 3 sources. Synthea also
  exports deceased patients, hence 328 and 3 461 patients in Gold.

Reproduce (development runner): `python scripts/perf_pipeline.py --label demo-cold --out docs/performance/demo-cold.json`
with the `HEALTHLAKE_*` variables of an empty database, then `python scripts/perf_api.py --api ... --key ...`, then
`python scripts/perf_report.py`.

## Results

### Generation
| Profile | Wall | Peak RSS | Batches |
|---|---|---|---|
| demo | 205 s | 1.32 GB | byte-identical to the earlier generation (same 3 batch ids) |
| extended | 1 271 s (21 min) | 1.45 GB | |

The first extended generation was **killed by the OOM killer at 5.7 GB** after 729 s: every Synthea bundle was
held in memory and parsed at once. Generation now streams the bundles from disk. That cut the peak to 1.45 GB, and
the demo batches stayed byte-identical (decision log, 2026-10-15).

### Pipeline
| | demo cold | demo warm | extended cold |
|---|---|---|---|
| Resources received | 160 111 | 160 111 | 1 791 707 |
| Ingestion of 3 batches | 210.8 s | 215.2 s | 1 640.0 s |
| ... validate + resolve + classify | 116.2 s | 123.8 s | 442.4 s |
| ... normalize | 29.7 s | 31.4 s | 333.8 s |
| ... load Silver | 42.0 s | 45.2 s | 625.5 s |
| Snapshot | 3.0 s | 3.0 s | 50.2 s |
| dbt build (models + 100 tests + indexes) | 16.9 s | 17.1 s | 133.8 s |
| dbt docs, gate, publish | 7.3 s | 7.0 s | 10.0 s |
| **Total** | **239.2 s** | **243.5 s** | **1 841.3 s (30.7 min)** |
| Peak RSS, largest process | 1.87 GB | 1.67 GB | 2.68 GB |
| Database size | 948 MB | 948 MB | 10.6 GB |
| Bronze (lake) | 271 MB | 271 MB | 2.85 GB |

Gold rows on the extended profile:
- 133 369 encounters
- 1 033 613 observations
- 453 617 components
- 83 577 conditions
- 106 009 prescriptions

### API, 5 concurrent clients
| | Aggregates p50 / p95 | Lists p50 / p95 | Throughput | Errors |
|---|---|---|---|---|
| demo cold | 52 / 68 ms | 56 / 77 ms | 64 req/s | 0 / 90 |
| demo warm | 56 / 68 ms | 60 / 76 ms | 84 req/s | 0 / 1 800 |
| extended cold | 52 / 60 ms | 56 / 72 ms | 60 req/s | 0 / 90 |
| extended warm | 56 / 68 ms | 60 / 76 ms | 83 req/s | 0 / 1 800 |
| *extended warm, before the fix below* | *80 / 1 020 ms* | *260 / 772 ms* | *17 req/s* | *0 / 1 800* |

Target "aggregates p95 < 500 ms": **met on both profiles**, and not met before the fix.

## Analysis
**The extended load test found a real defect.** On 1 M observations, `/v1/summary` took 892 ms at p50: it counted
every fact table on each call. Lists filtered by code took 616 ms, because Gold tables had no index.

The fix has three parts:
1. Headline counts are now precomputed per release (`agg_summary`, checked against the facts by a dbt test).
   A release is immutable, so counting once at build time is enough.
2. dbt post-hooks create indexes that match each list's keyset order and equality filters, then run `ANALYZE`.
3. The `code` filter is resolved to the release's code key first, so the index returns rows already in keyset
   order.

An intermediate run, with indexes but without step 3, still had observations by code at 171 ms p50, because
PostgreSQL sorted about 24 000 joined rows. With step 3 the query takes under 1 ms in the database.

**The API floor under load is CPU contention, not the queries.** A single request takes about 8 ms (curl,
`/v1/patients`). Under load, 5 client threads, 2 uvicorn workers and PostgreSQL share 2 vCPUs, so p50 settles
around 55 ms whatever the endpoint and the profile. Cold p99 values (110-130 ms) are the first reads after the
cache drop.

**Scaling, demo to extended (11.2 times the resources):**

| Step | Ratio | Behaviour |
|---|---|---|
| Ingestion overall | 7.8 times | Sublinear |
| Validation | 3.8 times | Sublinear: the HL7 validator audits a fixed-size sample, and its JVM start-up is a fixed cost |
| Normalisation | 11.2 times | Linear |
| Silver load | 14.9 times | Slightly superlinear: index maintenance on `silver.resource_version`, `reference` and `coding` (3.8 M codings) grows with table size |
| dbt build | 7.9 times | Sublinear |

The load step is the first candidate for work: copy into unindexed staging, then index, or partition by source.

**The snapshot was the second defect found by the extended run.** It took 200 s at 1.8 M members:
- about 95 s of row-by-row foreign-key checks;
- nested-loop joins planned on a table with no statistics yet.

Migration 0008 drops that foreign key: members come from a join with the referenced table in the same statement,
and resource versions are never deleted. The build also disables nested loops for its own transaction. Result:
**50 s**, a 4 times gain.

The measured runs predate migration 0009, which adds an `ANALYZE` of the snapshot tables at the end of every
snapshot build. It was found by the demo scenarios: a second release had been planned on stale statistics. That
`ANALYZE` takes 2.2 s on the extended snapshot, measured separately.

**Cold and warm are close for the pipeline** (239 s and 244 s on demo): it is CPU-bound, not I/O-bound.
Run-to-run variation on this shared VM is large. Earlier demo runs, with the same ingestion code, took
274/268 s and 314/254 s. Treat differences under about 15 % as noise.

**Memory.** The largest process stays under 2.7 GB on the extended profile. For the central batch, the Python
process peaks at 2.68 GB, and the validator JVM is capped at 2 GB. Resolution holds per-resource metadata for the
whole batch, so memory grows with batch size. A profile 3 times larger would need chunked resolution (listed in
remaining-work.md).

## Not measured
| Item | Why |
|---|---|
| Extended profile warm pipeline | Disk budget of the sandbox: one 10.6 GB database at a time. Cold vs warm is measured on demo. |
| Containers, PostgreSQL 17, Airflow scheduling overhead | No Docker daemon in the sandbox. Airflow was run for real on the test profile only (phase 7). |
| Several batches in parallel | The ingestion pool has one slot by design (one batch at a time). |
| Dashboard rendering time | Not measured. The dashboard caches API answers per release. |

## Files
| File | Content |
|---|---|
| `generation-demo.json`, `generation-extended.json` | `healthlake generate` timing and the batch ids |
| `demo-cold.json`, `demo-warm.json`, `extended-cold.json` | Pipeline runs |
| `api-demo-{cold,warm}.json`, `api-extended-{cold,warm}.json` | API runs |
| `api-extended-before-indexes.json` | API run before the fix, copied from its command output |
| `results.md` | Generated tables |
