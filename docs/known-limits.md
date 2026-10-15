# Known limits

> HealthLake is a technical demonstration using synthetic data only.
> It is not a certified healthcare platform and is not intended or
> authorized to process real personal health data.

These limits are deliberate scope choices or facts not verified yet. They are stated so that nobody reads the
project as more than it is.

## Not verified
| Item | Why | How to verify |
|---|---|---|
| Docker Desktop on Windows (the intended host) | The stack is verified in CI on Linux only | `python scripts/bootstrap.py`, `make build up demo` from PowerShell |
| arm64 images (Apple Silicon) | CI builds amd64 only (the Temurin checksum for arm64 is pinned but unused) | `docker compose build` on an arm64 machine |
| Java 17 | Temurin 21 is used (justified in docs/deployment.md) | n/a by design |
| Extended profile through Airflow in containers | CI time budget; measured with the local runner | `docker compose run --rm synthea --profile extended --revision 1` |

## Scope and design limits
- **Not a medical product.** No clinical decision support, no certification (HDS, HIPAA, ISO 27001), no consent
  management, no audit trail suitable for real patient data.
- **Single node.** One PostgreSQL instance, LocalExecutor, no high availability, no horizontal scaling.
- **Validation depth.** Every resource gets HealthLake's structural validation. The official HL7 validator runs
  on a sample (policy in `config/hl7-validation-policy.json`), because validating everything with it would take
  hours on a laptop ([ADR 0003](../architecture/adr/0003-validation-tiers.md)).
- **Terminology.** Codes are checked for presence and system. There is no terminology server, so a syntactically
  valid but unknown SNOMED CT code is not detected. Coverage is reported, not enforced.
- **Identity.** No cross-source patient matching (no MPI): identities are resolved only within a source namespace.
  Three patients in three sources are three patients.
- **Medication.** A MedicationRequest that references a Medication delivered in an earlier batch is not coded
  from it; only references within the same batch are used.
- **Business formats.** The CSV (`horizon-csv-v1`) and JSON (`horizon-json-v1`) formats are HealthLake's own
  fictional formats, derived from Synthea FHIR output. They are not Synthea's CSV exporter.
- **Time.** All timestamps are stored and served in UTC; Gold day boundaries are UTC days.
- **Swagger UI** loads its JavaScript and CSS from a CDN (FastAPI default). `/openapi.json` and the API work offline.
- **Dashboard** is a Streamlit demo app, with no user accounts; it uses one API key with `read` + `ops` scopes.
- **API keys** are static and rotated by `scripts/bootstrap.py --rotate-api-keys`; there is no OAuth/OIDC.
- **Retention.** Old releases are purged by count; Bronze is kept forever (no deletion policy).
- **Performance.** Measured on a 2-vCPU VM; see [performance/README.md](performance/README.md) for numbers and
  what they do and do not show.
