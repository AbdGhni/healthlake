# Data contract: batches, identifiers, formats

HealthLake is a technical demonstration using synthetic data only.
It is not a certified healthcare platform and is not intended or
authorized to process real personal health data.

## Landing layout
```
landing/<source_id>/rev-<NNNNNN>/   finalized batch (manifest.json present)
landing/<source_id>/.tmp-rev-<N>/   being written, ignored by discovery
```
Writers (`healthlake.generation.batch_writer`) write data files, then `manifest.json` last (fsync), then
rename the temp directory atomically. Discovery only reads directories that contain a manifest.

## Manifest (manifest_version 1)
| Field | Rule |
|---|---|
| manifest_version | 1 |
| source_id | registered in `ctl.source`, matches the parent directory |
| source_revision | integer > 0, business order of revisions |
| source_format | `fhir-r4-bundle`, `horizon-csv-v1`, `horizon-json-v1` |
| schema_version | free text, e.g. `fhir-4.0.1` |
| synthetic | must be `true` |
| reference_date | YYYY-MM-DD |
| generator | name, version, parameters (seeds, population, jar SHA-256, ...) |
| files | sorted by path; each: relative POSIX path, mime_type, size_bytes, sha256 |

Refused: absolute paths, `..`, `.`, empty segments, backslashes, colons, symbolic links, special files,
undeclared files, missing files, size or hash mismatch, limits exceeded (per file 512 MiB, 10 000 files,
8 GiB per batch, 5 000 000 resources; see `healthlake.ingestion.manifest.Limits`).
The same `(source_id, source_revision)` with different content is a blocking conflict (exit code 5).

## Canonical JSON and identifiers
Canonical JSON is a HealthLake convention, not RFC 8785:
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` encoded in UTF-8.

| Identifier | Definition |
|---|---|
| batch_id | SHA-256 of the canonical logical manifest (the validated manifest model) |
| processing_id | SHA-256 of canonical `{batch_id, code, mapping, validation}` versions |
| attempt_id | random UUIDv4, operational only |
| entity_id | UUIDv5(namespace(source_id), "<ResourceType>/<source id>"), namespace = UUIDv5(UUIDv5(URL, "urn:healthlake"), "source:<source_id>") |
| resource_version_id | SHA-256 of canonical `{entity_id, resource_sha256, mapping}` |
| resource_sha256 | SHA-256 of the canonical resource JSON |
| release_id / snapshot_id | SHA-256 of sorted processing ids + code version (phase 6) |

No identifier contains an operational timestamp. The same business id in two sources gives two entities.

## Business formats (HealthLake's own fictional formats, not Synthea formats)
They are derived deterministically from three Synthea populations by `healthlake.generation.derive`.
Names, addresses and telecom are not exported.

- `horizon-csv-v1` (horizon-nord): `organizations.csv`, `practitioners.csv`, `patients.csv`, `encounters.csv`,
  `conditions.csv`, `observations.csv`, `observation_components.csv`, `medication_requests.csv`.
  Exact headers are in `healthlake.generation.derive.CSV_COLUMNS`; any other header is a fatal file error.
  Practitioners are referenced by NPI (`practitioner_npi`, `requester_npi`).
- `horizon-json-v1` (horizon-sud): `reference-data.json` (organizations, practitioners) and
  `records/records-NNNN.json` (patients with nested encounters, which nest observations with components,
  conditions and medication requests).
- `fhir-r4-bundle` (horizon-central): Synthea 4.0.0 transaction bundles, plus hospital and practitioner
  batch bundles. All resource types are kept in Silver; seven are projected.

## Occurrence outcomes
received = accepted + deduplicated + rejected + out_of_scope, assigned in this priority:
1. rejected: own validation error, or a required/ambiguous/wrongly typed reference, or patient/encounter
   mismatch, or a dependency on a rejected resource, or same id with different content in one revision;
2. deduplicated: same identity and same content seen earlier in the batch;
3. out_of_scope: valid, kept in Silver JSON, not projected (Claim, Procedure, ...);
4. accepted: valid and projected.
