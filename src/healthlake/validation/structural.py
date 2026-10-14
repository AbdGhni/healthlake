"""Structural validation of projected FHIR R4 resources (validation version val-1).

What is checked: required elements used by HealthLake, FHIR R4 required value sets for status-like
codes, primitive formats (id, date, dateTime), value[x] cardinality, period ordering.
What is not checked here: full StructureDefinition conformance and terminology bindings (see hl7.py).
"""

from __future__ import annotations

from typing import Any

from healthlake.adapters.base import Issue
from healthlake.fhirtypes import ID_RE, parse_date, parse_datetime

PROJECTED = {
    "Patient",
    "Encounter",
    "Condition",
    "Observation",
    "MedicationRequest",
    "Organization",
    "Practitioner",
}
GENDER = {"male", "female", "other", "unknown"}
ENCOUNTER_STATUS = {
    "planned",
    "arrived",
    "triaged",
    "in-progress",
    "onleave",
    "finished",
    "cancelled",
    "entered-in-error",
    "unknown",
}
OBS_STATUS = {
    "registered",
    "preliminary",
    "final",
    "amended",
    "corrected",
    "cancelled",
    "entered-in-error",
    "unknown",
}
MR_STATUS = {"active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft", "unknown"}
MR_INTENT = {
    "proposal",
    "plan",
    "order",
    "original-order",
    "reflex-order",
    "filler-order",
    "instance-order",
    "option",
}
COND_CLINICAL = {"active", "recurrence", "relapse", "inactive", "remission", "resolved"}
VALUE_KEYS = (
    "valueQuantity",
    "valueCodeableConcept",
    "valueString",
    "valueBoolean",
    "valueInteger",
    "valueRange",
    "valueRatio",
    "valueSampledData",
    "valueTime",
    "valueDateTime",
    "valuePeriod",
)


class _V:
    def __init__(self, loc: str, file_sha: str | None) -> None:
        self.loc, self.file_sha, self.issues = loc, file_sha, []  # type: ignore[var-annotated]

    def err(self, check: str, cause: str, msg: str, severity: str = "error") -> None:
        self.issues.append(Issue(check, severity, cause, msg, self.loc, self.file_sha))


def _code(cc: Any) -> str | None:
    if isinstance(cc, dict):
        for c in cc.get("coding") or []:
            if isinstance(c, dict) and c.get("code"):
                return str(c["code"])
    return None


def _check_date(v: _V, res: dict[str, Any], key: str, kind: str = "dateTime") -> None:
    if key in res:
        raw = res[key]
        ok = isinstance(raw, str) and (parse_datetime(raw) if kind == "dateTime" else parse_date(raw))
        if not ok:
            v.err("fhir.datatype", "invalid_" + kind.lower(), f"{key} is not a valid FHIR {kind}")


def _has_ref(res: dict[str, Any], key: str) -> bool:
    r = res.get(key)
    return isinstance(r, dict) and bool(r.get("reference") or r.get("identifier"))


def validate_resource(rtype: str, res: dict[str, Any], loc: str, file_sha: str | None) -> list[Issue]:
    v = _V(loc, file_sha)
    rid = res.get("id")
    if not isinstance(rid, str) or not ID_RE.match(rid):
        v.err("fhir.id", "invalid_id", "resource id missing or not a FHIR id")
    if res.get("resourceType") != rtype:
        v.err("fhir.structure", "type_mismatch", "resourceType mismatch")
    meta = res.get("meta")
    if meta is not None and not isinstance(meta, dict):
        v.err("fhir.structure", "invalid_meta", "meta must be an object")
    if rtype not in PROJECTED:
        return v.issues
    if rtype == "Patient":
        if "gender" in res and res["gender"] not in GENDER:
            v.err("fhir.valueset", "invalid_gender", "gender not in AdministrativeGender")
        _check_date(v, res, "birthDate", "date")
        _check_date(v, res, "deceasedDateTime")
    elif rtype == "Encounter":
        if res.get("status") not in ENCOUNTER_STATUS:
            v.err("fhir.valueset", "invalid_status", "Encounter.status missing or invalid")
        if not isinstance(res.get("class"), dict) or not res["class"].get("code"):
            v.err("fhir.required", "missing_class", "Encounter.class is required")
        if not _has_ref(res, "subject"):
            v.err("fhir.required", "missing_subject", "Encounter.subject is required by HealthLake")
        period = res.get("period") or {}
        start = parse_datetime(period["start"]) if isinstance(period.get("start"), str) else None
        end = parse_datetime(period["end"]) if isinstance(period.get("end"), str) else None
        if "start" in period and start is None:
            v.err("fhir.datatype", "invalid_datetime", "period.start invalid")
        if "end" in period and end is None:
            v.err("fhir.datatype", "invalid_datetime", "period.end invalid")
        if start and end and start.instant and end.instant and end.instant < start.instant:
            v.err("temporal.period", "period_inverted", "Encounter.period.end is before start")
    elif rtype == "Condition":
        if not _code(res.get("code")):
            v.err("fhir.required", "missing_code", "Condition.code is required by HealthLake")
        if not _has_ref(res, "subject"):
            v.err("fhir.required", "missing_subject", "Condition.subject is required")
        cs = _code(res.get("clinicalStatus"))
        if cs is not None and cs not in COND_CLINICAL:
            v.err("fhir.valueset", "invalid_clinical_status", "clinicalStatus not in R4 value set")
        for k in ("onsetDateTime", "abatementDateTime", "recordedDate"):
            _check_date(v, res, k)
        on = parse_datetime(res["onsetDateTime"]) if isinstance(res.get("onsetDateTime"), str) else None
        ab = parse_datetime(res["abatementDateTime"]) if isinstance(res.get("abatementDateTime"), str) else None
        if on and ab and on.instant and ab.instant and ab.instant < on.instant:
            v.err("temporal.period", "period_inverted", "abatement before onset")
    elif rtype == "Observation":
        if res.get("status") not in OBS_STATUS:
            v.err("fhir.valueset", "invalid_status", "Observation.status missing or invalid")
        if not _code(res.get("code")):
            v.err("fhir.required", "missing_code", "Observation.code is required")
        if not _has_ref(res, "subject"):
            v.err("fhir.required", "missing_subject", "Observation.subject is required by HealthLake")
        _check_date(v, res, "effectiveDateTime")
        _check_value(v, res, "Observation")
        for i, comp in enumerate(res.get("component") or []):
            if not isinstance(comp, dict) or not _code(comp.get("code")):
                v.err("fhir.required", "component_missing_code", f"component[{i}].code is required")
                continue
            _check_value(v, comp, f"component[{i}]")
    elif rtype == "MedicationRequest":
        if res.get("status") not in MR_STATUS:
            v.err("fhir.valueset", "invalid_status", "MedicationRequest.status missing or invalid")
        if res.get("intent") not in MR_INTENT:
            v.err("fhir.valueset", "invalid_intent", "MedicationRequest.intent missing or invalid")
        if "medicationCodeableConcept" not in res and not _has_ref(res, "medicationReference"):
            v.err("fhir.required", "missing_medication", "medication[x] is required")
        if not _has_ref(res, "subject"):
            v.err("fhir.required", "missing_subject", "MedicationRequest.subject is required")
        _check_date(v, res, "authoredOn")
    return v.issues


def _check_value(v: _V, el: dict[str, Any], where: str) -> None:
    present = [k for k in VALUE_KEYS if k in el]
    if len(present) > 1:
        v.err("fhir.cardinality", "multiple_values", f"{where} has several value[x]")
    if present and "dataAbsentReason" in el:
        v.err("fhir.invariant", "obs6_value_and_absent_reason", f"{where} has value[x] and dataAbsentReason")
    if "valueQuantity" in el:
        q = el["valueQuantity"]
        if not isinstance(q, dict) or not isinstance(q.get("value"), int | float) or isinstance(q.get("value"), bool):
            v.err("fhir.datatype", "invalid_quantity", f"{where}.valueQuantity.value must be a number")
    if "valueDateTime" in el and not (isinstance(el["valueDateTime"], str) and parse_datetime(el["valueDateTime"])):
        v.err("fhir.datatype", "invalid_datetime", f"{where}.valueDateTime invalid")
    if "valueBoolean" in el and not isinstance(el["valueBoolean"], bool):
        v.err("fhir.datatype", "invalid_boolean", f"{where}.valueBoolean must be boolean")
