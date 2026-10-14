# Runbook: unresolved or inconsistent reference

**Symptom**: issues with `check_id = 'reference.resolution'` or `consistency.patient_encounter`.

## Causes (from `cause_code`)
| cause_code | Meaning | Blocking for the resource |
|---|---|---|
| reference_unresolved | target not in this batch nor in Silver for the same source | yes if required (subject) |
| reference_ambiguous | identifier matches several identities | yes |
| wrong_target_type | e.g. Observation.subject points to an Encounter | yes |
| reference_external | absolute URL outside the declared `fhir_base_url`; never fetched | yes if required |
| identifier_system_unknown | identifier system not an identity system of that type (`config/sources.json`) | yes if required |
| contained_not_found | `#id` not in `contained` | yes if required |
| patient_encounter_mismatch | subject differs from the referenced Encounter's patient | yes |

Optional references that do not resolve (for example `serviceProvider`) are warnings: the resource is kept and
the reference is not projected.

## Diagnose
```sql
SELECT cause_code, locator, message FROM quality.issue
WHERE processing_id = '<processing_id>' AND check_id IN ('reference.resolution','consistency.patient_encounter')
ORDER BY issue_id LIMIT 50;
```
Resolution is always inside one source namespace: HealthLake never matches patients across sources, by name or by
birth date.

## Fix
- Missing target: the referenced resource must be delivered in the same batch or an earlier loaded batch of the
  same source. Deliver it in a new revision.
- Ambiguity: two identities share an identity identifier, which is itself an `identity.conflict` (blocking).
  Fix the source data.
