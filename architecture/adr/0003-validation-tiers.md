# ADR 0003: two validation tiers

Status: accepted (2026-10-14)

## Context
The official HL7 validator (validator_cli 7.0.1) was measured in the sandbox: ~20 s start-up, ~30 s per
2 MB Synthea patient bundle, ~1 GB heap. Full validation of the demo profile (110 bundles for one source)
would take about 50 minutes, against a pipeline budget of 10 minutes for 100 patients.

## Decision
1. **Blocking tier, every resource:** `healthlake.validation.structural` (version `val-1`). It checks resource
   ids, required elements used downstream, R4 required value sets for status-like codes (gender,
   Encounter/Observation/MedicationRequest status, intent, Condition clinical status), primitive formats
   (id, date, dateTime with mandatory zone), value[x] cardinality, invariant obs-6, period ordering.
   Errors reject the occurrence (quarantine) and feed the reject-rate gate.
2. **Audit tier, deterministic sample:** the HL7 validator runs offline (`-tx n/a`, pre-loaded packages)
   on the reference bundles plus the first patient bundle (FHIR source), or on the first 300 adapted
   resources wrapped in a collection Bundle (CSV/JSON sources). Findings become `warning` issues with
   check `fhir.hl7_validator` and a `fhir.hl7_validator_sample` check result. Two message families are
   reclassified by `config/hl7-validation-policy.json` (Synthea's unpublished extensions; US Core
   target-profile matching on bundle references).

## Consequences
- HealthLake does not claim that every resource conforms to every StructureDefinition.
- Terminology: codes are not validated against a terminology server. Required bindings that HealthLake
  relies on are enforced in tier 1; the rest is reported as coverage, not as validity.
- Measured on the test fixtures, the validator flags real defects (conditional references outside a
  transaction bundle, missing vital-signs category), which shows the audit is not a formality.
