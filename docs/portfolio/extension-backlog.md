# Extension backlog

Ideas that would extend HealthLake, ordered by value for effort. None is started.

| # | Item | Why | Size |
|---|---|---|---|
| 1 | Verify the Compose stack on a Docker host and record the run | Closes the main "not verified" item | S |
| 2 | Serve Swagger UI assets locally | Fully offline API docs | S |
| 3 | Use Medication from earlier batches for `medicationReference` | Removes a known coding gap | S |
| 4 | Incremental dbt models for large facts (observations) | Faster releases as history grows | M |
| 5 | Parallel validation workers (process pool per file chunk) | The validate/resolve step dominates pipeline time | M |
| 6 | Terminology checks against a local subset (LOINC/SNOMED CT value sets) | Detect unknown codes, not only missing ones | M |
| 7 | OpenTelemetry traces across CLI steps and API requests | Per-request and per-step latency breakdown | M |
| 8 | Data contracts as JSON Schema published per source format version | Producers can validate before delivery | M |
| 9 | Great Expectations or Soda checks alongside dbt tests | Comparison of quality frameworks | M |
| 10 | Object storage (MinIO / S3) for the RawStore | Closer to a cloud data lake | M |
| 11 | Cross-source patient matching (probabilistic MPI) with review queue | Realistic identity problem, clearly flagged as synthetic | L |
| 12 | FHIR Bulk Data `$export` source | Standard ingestion path for real FHIR servers | L |
| 13 | Kubernetes deployment (Helm chart, KubernetesExecutor) | Scale-out story | L |
