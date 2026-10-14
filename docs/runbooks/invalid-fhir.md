# Runbook: invalid FHIR resources / processing blocked by quarantine

**Symptom**: task `classify_quality` fails (exit 3) with `processing_blocked`, or resources are quarantined.

## Diagnose
1. Summary of the attempt (issue counts by check and cause):
   ```
   healthlake inspect --attempt-id <attempt_id>
   ```
2. Gate results:
   ```sql
   SELECT check_id, status, observed, threshold, details FROM quality.check_result
   WHERE scope = 'processing' AND scope_id = '<processing_id>';
   ```
3. Individual issues with their exact location (JSON pointer or CSV line):
   ```sql
   SELECT check_id, severity, cause_code, locator, source_resource_id, message
   FROM quality.issue WHERE processing_id = '<processing_id>' AND severity IN ('fatal','error')
   ORDER BY issue_id LIMIT 50;
   ```
4. Dependency chains: rows with `cause_code = 'dependency_rejected'` point to their cause with `caused_by_issue_id`.

## Interpret
- `format.*` fatal: a file could not be parsed (truncated JSON, wrong CSV header). Whole processing blocked.
- `fhir.*` errors: the resource is rejected; it is a quarantine row, not a pipeline failure.
- `quarantine.reject_rate_new` failed: more than 1 % of new resources rejected (demonstration policy).
- `identity.invalid_updates` failed: an identity already in Silver received invalid content; blocked by design.
- `fhir.hl7_validator` warnings: audit sample findings (ADR 0003), never blocking.

## Fix
Produce a corrected **new revision** of the source. The blocked processing stays `blocked` for traceability.
Optionally record the decision:
```sql
UPDATE quality.issue SET resolution_status='superseded', resolution_note='fixed in revision N',
  resolved_by_processing_id='<new processing_id>' WHERE processing_id='<blocked processing_id>';
```
