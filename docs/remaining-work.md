# Remaining work

All phases are done. What remains needs a Docker host or your authorisation (push to GitHub, which also runs CI).

Known gaps (also in docs/known-limits.md):
- Unverified on this machine: Docker build/up, Airflow in containers, PostgreSQL 17, Java 17 (Temurin 21 used).
- Medication from earlier batches is not used to code MedicationRequest.medicationReference.
- Swagger UI (`/docs`) loads its JS/CSS from a CDN (FastAPI default); offline the OpenAPI JSON still works.
- Extended profile measured cold only (disk budget of the sandbox: one 10.5 GB database at a time); the warm/cold
  difference is measured on the demo profile.
- Processing memory grows with batch size (central batch of the extended profile: 2.7 GB peak RSS in Python, plus
  the HL7 validator JVM capped at 2 GB). A larger profile would need chunked resolution.
