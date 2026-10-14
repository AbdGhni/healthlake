# Quality catalogue (qc-1)

Generated from `config/quality-catalog.json` by `scripts/gen_quality_catalog.py`. Do not edit by hand.

> Demonstration policy on synthetic data. Thresholds are engineering thresholds, not medical thresholds.

| Check | Category | Scope | Severity | Blocking | Threshold | Description | Implementation |
|---|---|---|---|---|---|---|---|
| `batch.manifest` | format | batch | fatal | yes |  | Manifest parses and follows contract v1 (synthetic=true, sorted safe relative paths, limits). | healthlake.ingestion.manifest.parse_manifest; discovery reports the error, batch not registered |
| `batch.integrity` | hash | batch | fatal | yes |  | Every declared file exists with its size and SHA-256; no undeclared file, no symlink. | healthlake.ingestion.registry.verify_batch; ctl.batch.status=invalid |
| `batch.revision_conflict` | uniqueness | batch | fatal | yes |  | Same source_id and source_revision registered with different content. | registry.register_batch; exit code 5 |
| `bronze.reconciliation` | hash | store | error | no |  | Every registered Bronze object exists and matches its hash; unregistered objects are listed. | healthlake verify-bronze |
| `format.json` | format | file | fatal | yes |  | JSON file parses (UTF-8). | adapters |
| `format.fhir_bundle` | format | file | fatal | yes |  | File is a FHIR Bundle of a supported type. | adapters.fhir_bundle |
| `format.csv` | format | file | fatal | yes |  | CSV file is expected, UTF-8, parseable, with the exact horizon-csv-v1 header. | adapters.horizon |
| `format.row` | format | resource | error | no |  | A row/record can be mapped to FHIR (column count, numbers, booleans). | adapters.horizon |
| `format.fatal_files` | format | processing | fatal | yes |  | Gate: no fatal file issue in the processing. | quality.processing_gate |
| `fhir.id` | fhir | resource | error | no |  | Resource id present and a valid FHIR id. | validation.structural |
| `fhir.structure` | fhir | resource | error | no |  | resourceType consistent, meta is an object, entry has a resource. | validation.structural |
| `fhir.required` | completeness | resource | error | no |  | Elements required by FHIR R4 or by HealthLake analytics (subject, code, class, medication[x]). | validation.structural |
| `fhir.valueset` | fhir | resource | error | no |  | R4 required value sets: gender, statuses, intent, clinical status. | validation.structural |
| `fhir.datatype` | fhir | resource | error | no |  | date/dateTime formats (zone required with a time), numbers, booleans. | validation.structural |
| `fhir.cardinality` | fhir | resource | error | no |  | At most one value[x]. | validation.structural |
| `fhir.invariant` | fhir | resource | error | no |  | obs-6: dataAbsentReason only without value[x]. | validation.structural |
| `fhir.hl7_validator` | fhir | resource | warning | no |  | Official HL7 validator finding on the audit sample (ADR 0003). | validation.hl7 |
| `fhir.hl7_validator_sample` | fhir | processing | warning | no |  | Audit status: number of unexplained HL7 validator errors in the sample. | validation.hl7 + quality.processing_gate |
| `temporal.period` | temporal | resource | error | no |  | Encounter end >= start; Condition abatement >= onset. | validation.structural |
| `value.extreme` | extremes | resource | warning | no |  | Quantity outside the plausibility range of config/plausibility.json (same code and unit only). | validation.plausibility |
| `reference.resolution` | referential | resource | error | no |  | Required references resolve; ambiguous, wrongly typed or external references refused (optional unresolved = warning). | pipelines.resolve |
| `reference.dependency` | referential | resource | error | no |  | Reference to a resource rejected in the same batch (cause recorded). | pipelines.resolve |
| `consistency.patient_encounter` | patient-encounter | resource | error | no |  | Subject equals the patient of the referenced Encounter. | pipelines.resolve |
| `identity.conflict` | uniqueness | processing | fatal | yes |  | One identity-system identifier claimed by two identities (same source). | pipelines.resolve |
| `identity.content_conflict` | uniqueness | processing | fatal | yes |  | Same identity twice with different content in one revision. | pipelines.resolve |
| `identity.invalid_update` | uniqueness | processing | fatal | yes |  | Invalid content for an identity already in Silver. | pipelines.resolve |
| `identity.conflicts` | uniqueness | processing | fatal | yes | 0 | Gate: 0 identity or content conflict. | quality.processing_gate |
| `identity.invalid_updates` | uniqueness | processing | fatal | yes | 0 | Gate: 0 invalid update. | quality.processing_gate |
| `quarantine.reject_rate_new` | completeness | processing | fatal | yes | 0.01 | Gate: rejected new resources / received new resources <= 1 %. | quality.processing_gate |
| `reconciliation.occurrences` | reconciliation | processing | fatal | yes | 0 | received = accepted + deduplicated + rejected + out_of_scope. | quality.processing_gate |
| `dbt.tests` | reconciliation | release | fatal | yes | 0 | All dbt tests pass (unique, not_null, relationships, patient/encounter, periods, aggregates, fan-out, components). | release.gate |
| `dbt.models` | completeness | release | fatal | yes | 0 | All dbt models built. | release.gate |
| `release.schema_complete` | completeness | release | fatal | yes | 0 | The 15 Gold marts exist. | release.gate |
| `release.snapshot_dangling_references` | referential | release | fatal | yes | 0 | Every reference of the snapshot points into the snapshot. | release.gate |
| `release.gold_reconciles_snapshot` | reconciliation | release | fatal | yes | 0 | Gold row count per projected type equals snapshot members. | release.gate |
| `release.processings_passed` | reconciliation | release | fatal | yes | 0 | Every included processing passed its own gate. | release.gate |
| `release.terminology_coverage` | terminology | release | warning | no | 0.95 | Share of codings of the snapshot whose system is in known_code_systems. Codes are NOT validated against a terminology server. | release.gate (observations) |
| `release.freshness_clinical_data` | freshness | release | warning | no | 90 | Days between the batches' reference_date and the latest encounter start. | release.gate (observations) |
| `release.completeness_encounter_end` | completeness | release | info | no |  | Share of encounters with an end instant (informational). | release.gate (observations) |
| `release.completeness_observation_effective` | completeness | release | info | no |  | Share of observations with an effective instant (informational). | release.gate (observations) |

## Reconciliation

Per processing: `received = accepted + deduplicated + rejected + out_of_scope`. Categories are disjoint and
assigned in priority order rejected > deduplicated > out_of_scope > accepted (see docs/data-contract.md).

## Quarantine

Every error/fatal/warning is a row of `quality.issue` with processing_id, attempt_id, file hash, locator
(JSON pointer or `file.csv#line=N`), source identity, check, severity, cause code, message,
`caused_by_issue_id` (dependency cause), resolution status and the processing that resolved it.
A correction is a new source revision; Bronze files are never modified.

## Terminology (what is and is not checked)

- Checked on every resource: R4 required value sets used by HealthLake (gender, statuses, intent, clinical status).
- Measured per release: share of codings whose system URI is one of the known systems below.
- Sample audit: the HL7 validator runs offline (`-tx n/a`), so it cannot validate SNOMED CT, LOINC or RxNorm codes.
- Not checked: existence of a code in its code system, display text correctness, concept status.

Known systems: `http://snomed.info/sct`, `http://loinc.org`, `http://www.nlm.nih.gov/research/umls/rxnorm`, `http://terminology.hl7.org/CodeSystem/v3-ActCode`, `http://terminology.hl7.org/CodeSystem/condition-clinical`, `http://terminology.hl7.org/CodeSystem/condition-ver-status`, `http://terminology.hl7.org/CodeSystem/condition-category`, `http://terminology.hl7.org/CodeSystem/observation-category`, `http://terminology.hl7.org/CodeSystem/data-absent-reason`, `http://terminology.hl7.org/CodeSystem/v3-ParticipationType`, `http://terminology.hl7.org/CodeSystem/organization-type`, `http://terminology.hl7.org/CodeSystem/medicationrequest-category`, `http://unitsofmeasure.org`, `http://hl7.org/fhir/sid/cvx`, `http://www.ama-assn.org/go/cpt`, `urn:ietf:bcp:47`

## Plausibility ranges (plaus-1)

> Engineering plausibility ranges to flag likely unit or entry errors in synthetic data. Not clinical reference ranges.

| LOINC | Label | Unit | Min | Max |
|---|---|---|---|---|
| 8302-2 | Body height | cm | 30 | 250 |
| 29463-7 | Body weight | kg | 0.3 | 400 |
| 8867-4 | Heart rate | /min | 20 | 300 |
| 9279-1 | Respiratory rate | /min | 4 | 80 |
| 8310-5 | Body temperature | Cel | 25 | 45 |
| 8480-6 | Systolic blood pressure | mm[Hg] | 40 | 300 |
| 8462-4 | Diastolic blood pressure | mm[Hg] | 20 | 200 |
| 39156-5 | Body mass index | kg/m2 | 5 | 100 |
