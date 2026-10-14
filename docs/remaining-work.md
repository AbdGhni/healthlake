# Remaining work

Next: phase 7 (Airflow DAGs and crash points 4-7), 8 (quality catalogue, metrics), 9 (API), 10 (dashboard),
11 (Docker/compose/CI/backup), 12 (E2E, extended profile, performance), 13 (docs/portfolio), 14 (final check).

Known gaps to address:
- Medication from earlier batches is not used to code MedicationRequest.medicationReference.
- Unverified on this machine: PG17, Java 17, Docker images.
- Runbooks still to write with their components: 
- Swagger UI (`/docs`) loads its JS/CSS from a CDN (FastAPI default); offline the OpenAPI JSON still works.
