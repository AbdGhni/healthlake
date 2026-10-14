# Remaining work

Next: phase 7 (Airflow DAGs and crash points 4-7), 8 (quality catalogue, metrics), 9 (API), 10 (dashboard),
11 (Docker/compose/CI/backup), 12 (E2E, extended profile, performance), 13 (docs/portfolio), 14 (final check).

Known gaps to address:
- Work directory growth (939 MB for the demo profile): add retention/cleanup of `work/<processing_id>` after load.
- `report` and `backfill` CLI commands do not exist yet.
- Medication from earlier batches is not used to code MedicationRequest.medicationReference.
- Unverified on this machine: PG17, Java 17, Docker images.
