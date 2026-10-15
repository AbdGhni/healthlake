# Remaining work

All phases are done and the repository is published with a green CI (Docker stack, Airflow in containers,
PostgreSQL 17). What remains is a run on Docker Desktop for Windows.

Known gaps (also in docs/known-limits.md):
- Not verified: Docker Desktop on Windows, arm64 images, Java 17 (Temurin 21 used).
- Medication from earlier batches is not used to code MedicationRequest.medicationReference.
- Swagger UI (`/docs`) loads its JS/CSS from a CDN (FastAPI default); offline the OpenAPI JSON still works.
- Extended profile measured cold only (disk budget of the sandbox: one 10.5 GB database at a time); the warm/cold
  difference is measured on the demo profile.
- Processing memory grows with batch size (central batch of the extended profile: 2.7 GB peak RSS in Python, plus
  the HL7 validator JVM capped at 2 GB). A larger profile would need chunked resolution.
