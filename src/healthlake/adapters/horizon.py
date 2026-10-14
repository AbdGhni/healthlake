"""horizon-csv-v1 and horizon-json-v1 business formats -> FHIR R4 resources.

Both formats carry the same logical records; mapping functions are shared. References use
relative `Type/id` within the source namespace, practitioners are referenced by NPI identifier.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from collections.abc import Callable, Iterator
from functools import partial
from typing import Any

from healthlake.adapters.base import NPI, AdaptedResource, Issue, cc, ident_ref, prune, ref
from healthlake.generation.derive import CSV_COLUMNS

CLASS_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
COND_CLINICAL = "http://terminology.hl7.org/CodeSystem/condition-clinical"
COND_VER = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
COND_CAT = "http://terminology.hl7.org/CodeSystem/condition-category"
OBS_CAT = "http://terminology.hl7.org/CodeSystem/observation-category"
DAR = "http://terminology.hl7.org/CodeSystem/data-absent-reason"
UCUM = "http://unitsofmeasure.org"


class RowError(ValueError):
    pass


def _bool(v: str | None) -> bool | None:
    if v in (None, ""):
        return None
    if v in ("true", "false"):
        return v == "true"
    raise RowError(f"invalid boolean {v!r}")


def _number(v: str) -> int | float:
    try:
        return int(v)
    except ValueError:
        pass
    try:
        f = float(v)
    except ValueError:
        raise RowError(f"invalid number {v!r}") from None
    if f != f or f in (float("inf"), float("-inf")):
        raise RowError(f"invalid number {v!r}")
    return f


def _value(r: dict[str, Any]) -> dict[str, Any]:
    vt = r.get("value_type") or "none"
    v = r.get("value", "")
    out: dict[str, Any] = {}
    if vt == "quantity":
        q = prune({"value": _number(v), "unit": r.get("unit"), "code": r.get("unit_code")})
        if r.get("unit_code"):
            q["system"] = UCUM
        out["valueQuantity"] = q
    elif vt == "coded":
        out["valueCodeableConcept"] = cc(r.get("value_code_system"), r.get("value_code"), r.get("value_code_display"))
    elif vt == "string":
        out["valueString"] = v
    elif vt == "boolean":
        out["valueBoolean"] = _bool(v)
    elif vt == "integer":
        out["valueInteger"] = int(_number(v))
    elif vt == "datetime":
        out["valueDateTime"] = v
    elif vt != "none":
        raise RowError(f"unknown value_type {vt!r}")
    if r.get("data_absent_reason"):
        out["dataAbsentReason"] = cc(DAR, r["data_absent_reason"])
    return out


def organization(r: dict[str, Any]) -> dict[str, Any]:
    return prune(
        {
            "resourceType": "Organization",
            "id": r["organization_id"],
            "name": r.get("name"),
            "active": _bool(r.get("active")),
            "type": [cc("http://terminology.hl7.org/CodeSystem/organization-type", r.get("type_code"))]
            if r.get("type_code")
            else None,
        }
    )


def practitioner(r: dict[str, Any]) -> dict[str, Any]:
    return prune(
        {
            "resourceType": "Practitioner",
            "id": r["practitioner_id"],
            "identifier": [{"system": NPI, "value": r["npi"]}] if r.get("npi") else None,
            "gender": r.get("gender"),
            "active": _bool(r.get("active")),
        }
    )


def patient(r: dict[str, Any]) -> dict[str, Any]:
    return prune(
        {
            "resourceType": "Patient",
            "id": r["patient_id"],
            "gender": r.get("gender"),
            "birthDate": r.get("birth_date"),
            "deceasedDateTime": r.get("deceased_datetime"),
            "managingOrganization": ref("Organization", r.get("managing_organization_id")),
        }
    )


def encounter(r: dict[str, Any], patient_id: str) -> dict[str, Any]:
    part = ident_ref("Practitioner", NPI, r.get("practitioner_npi"))
    return prune(
        {
            "resourceType": "Encounter",
            "id": r["encounter_id"],
            "status": r.get("status"),
            "class": prune({"system": CLASS_SYSTEM, "code": r.get("class_code")}) if r.get("class_code") else None,
            "type": [cc(r.get("type_system"), r.get("type_code"), r.get("type_display"))]
            if r.get("type_code")
            else None,
            "subject": ref("Patient", patient_id),
            "participant": [{"individual": part}] if part else None,
            "period": prune({"start": r.get("start"), "end": r.get("end")}),
            "serviceProvider": ref("Organization", r.get("organization_id")),
        }
    )


def condition(r: dict[str, Any], patient_id: str) -> dict[str, Any]:
    return prune(
        {
            "resourceType": "Condition",
            "id": r["condition_id"],
            "clinicalStatus": cc(COND_CLINICAL, r.get("clinical_status")),
            "verificationStatus": cc(COND_VER, r.get("verification_status")),
            "category": [cc(COND_CAT, r.get("category"))] if r.get("category") else None,
            "code": cc(r.get("code_system"), r.get("code"), r.get("display")),
            "subject": ref("Patient", patient_id),
            "encounter": ref("Encounter", r.get("encounter_id")),
            "onsetDateTime": r.get("onset"),
            "abatementDateTime": r.get("abatement"),
            "recordedDate": r.get("recorded"),
        }
    )


def observation(r: dict[str, Any], patient_id: str, components: list[dict[str, Any]]) -> dict[str, Any]:
    comps = []
    for c in sorted(components, key=lambda c: int(c.get("ordinal", 0))):
        comps.append(prune({"code": cc(c.get("code_system"), c.get("code"), c.get("display")), **_value(c)}))
    return prune(
        {
            "resourceType": "Observation",
            "id": r["observation_id"],
            "status": r.get("status"),
            "category": [cc(OBS_CAT, r.get("category"))] if r.get("category") else None,
            "code": cc(r.get("code_system"), r.get("code"), r.get("display")),
            "subject": ref("Patient", patient_id),
            "encounter": ref("Encounter", r.get("encounter_id")),
            "effectiveDateTime": r.get("effective"),
            **_value(r),
            "component": comps or None,
        }
    )


def medication_request(r: dict[str, Any], patient_id: str) -> dict[str, Any]:
    return prune(
        {
            "resourceType": "MedicationRequest",
            "id": r["medication_request_id"],
            "status": r.get("status"),
            "intent": r.get("intent"),
            "medicationCodeableConcept": cc(
                r.get("medication_system"), r.get("medication_code"), r.get("medication_display")
            ),
            "subject": ref("Patient", patient_id),
            "encounter": ref("Encounter", r.get("encounter_id")),
            "requester": ident_ref("Practitioner", NPI, r.get("requester_npi")),
            "authoredOn": r.get("authored"),
        }
    )


def _emit(file_sha: str, loc: str, rtype: str, rid: str | None, build: Callable[[], dict[str, Any]]) -> AdaptedResource:
    try:
        res = build()
        return AdaptedResource(file_sha, loc, rtype, rid, res)
    except (RowError, KeyError, ValueError, TypeError) as exc:
        return AdaptedResource(
            file_sha,
            loc,
            rtype,
            rid or None,
            {"resourceType": rtype, **({"id": rid} if rid else {})},
            issues=[Issue("format.row", "error", "row_unmappable", str(exc), loc, file_sha)],
        )


ROW_TYPES = {
    "organizations.csv": ("Organization", "organization_id"),
    "practitioners.csv": ("Practitioner", "practitioner_id"),
    "patients.csv": ("Patient", "patient_id"),
    "encounters.csv": ("Encounter", "encounter_id"),
    "conditions.csv": ("Condition", "condition_id"),
    "observations.csv": ("Observation", "observation_id"),
    "medication_requests.csv": ("MedicationRequest", "medication_request_id"),
}


def adapt_csv_batch(files: list[tuple[str, str, bytes]]) -> Iterator[AdaptedResource | Issue]:
    """files: (relative path, sha256, bytes). All CSV files of the batch are needed together
    because observation components live in their own file."""
    parsed: dict[str, tuple[str, list[tuple[int, dict[str, str]]]]] = {}
    for path, sha, data in sorted(files):
        name = path.rsplit("/", 1)[-1]
        if name not in CSV_COLUMNS:
            yield Issue("format.csv", "fatal", "unknown_file", f"{path}: unexpected file", path, sha)
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            yield Issue("format.csv", "fatal", "encoding", f"{path}: {exc}", path, sha)
            continue
        reader = csv.reader(io.StringIO(text, newline=""))
        try:
            header = next(reader)
        except StopIteration:
            yield Issue("format.csv", "fatal", "empty_file", f"{path}: empty", path, sha)
            continue
        except csv.Error as exc:
            yield Issue("format.csv", "fatal", "csv_unparseable", f"{path}: {exc}", path, sha)
            continue
        if header != CSV_COLUMNS[name]:
            yield Issue("format.csv", "fatal", "header_mismatch", f"{path}: header does not match {name}", path, sha)
            continue
        rows: list[tuple[int, dict[str, str]]] = []
        line = 1
        try:
            for values in reader:
                line = reader.line_num
                if len(values) != len(header):
                    rows.append((line, {"__error__": f"expected {len(header)} columns, got {len(values)}"}))
                    continue
                rows.append((line, dict(zip(header, values, strict=True))))
        except csv.Error as exc:
            yield Issue("format.csv", "fatal", "csv_unparseable", f"{path} line {line}: {exc}", path, sha)
            continue
        parsed[name] = (sha, rows)
    comps: dict[str, list[dict[str, str]]] = defaultdict(list)
    if "observation_components.csv" in parsed:
        for _, row in parsed["observation_components.csv"][1]:
            if "__error__" not in row:
                comps[row["observation_id"]].append(row)
    for name, (rtype, key) in ROW_TYPES.items():
        if name not in parsed:
            continue
        sha, rows = parsed[name]
        for line, row in rows:
            loc = f"{name}#line={line}"
            if "__error__" in row:
                yield AdaptedResource(
                    sha,
                    loc,
                    rtype,
                    None,
                    {"resourceType": rtype},
                    issues=[Issue("format.row", "error", "row_shape", row["__error__"], loc, sha)],
                )
                continue
            rid = row.get(key) or None
            pid = row.get("patient_id", "")
            builders: dict[str, Callable[[], dict[str, Any]]] = {
                "Organization": partial(organization, row),
                "Practitioner": partial(practitioner, row),
                "Patient": partial(patient, row),
                "Encounter": partial(encounter, row, pid),
                "Condition": partial(condition, row, pid),
                "Observation": partial(observation, row, pid, comps.get(rid or "", [])),
                "MedicationRequest": partial(medication_request, row, pid),
            }
            yield _emit(sha, loc, rtype, rid, builders[rtype])


def adapt_json_file(path: str, sha: str, data: bytes) -> Iterator[AdaptedResource | Issue]:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        yield Issue("format.json", "fatal", "json_unparseable", f"{path}: {exc}", path, sha)
        return
    if not isinstance(doc, dict) or doc.get("schema") != "horizon-json-v1":
        yield Issue("format.json", "fatal", "schema_mismatch", f"{path}: not horizon-json-v1", path, sha)
        return
    for i, r in enumerate(doc.get("organizations", [])):
        yield _emit(
            sha,
            f"{path}#/organizations/{i}",
            "Organization",
            r.get("organization_id"),
            partial(organization, r),
        )
    for i, r in enumerate(doc.get("practitioners", [])):
        yield _emit(
            sha,
            f"{path}#/practitioners/{i}",
            "Practitioner",
            r.get("practitioner_id"),
            partial(practitioner, r),
        )
    kinds = (
        ("observations", "Observation", "observation_id"),
        ("conditions", "Condition", "condition_id"),
        ("medication_requests", "MedicationRequest", "medication_request_id"),
    )
    for i, p in enumerate(doc.get("patients", [])):
        base = f"{path}#/patients/{i}"
        pid = p.get("patient_id")
        yield _emit(sha, base, "Patient", pid, partial(patient, p))
        for j, e in enumerate(p.get("encounters", [])):
            eloc = f"{base}/encounters/{j}"
            yield _emit(sha, eloc, "Encounter", e.get("encounter_id"), partial(encounter, e, pid or ""))
            for kind, rtype, key in kinds:
                for k, item in enumerate(e.get(kind, [])):
                    item = {**item, "encounter_id": e.get("encounter_id")}
                    yield _emit(sha, f"{eloc}/{kind}/{k}", rtype, item.get(key), _builder(rtype, item, pid or ""))
        for kind, rtype, key in kinds:
            for k, item in enumerate(p.get(kind, [])):
                yield _emit(sha, f"{base}/{kind}/{k}", rtype, item.get(key), _builder(rtype, item, pid or ""))


def _builder(rtype: str, item: dict[str, Any], pid: str) -> Callable[[], dict[str, Any]]:
    if rtype == "Observation":
        return lambda: observation(item, pid, item.get("components", []))
    if rtype == "Condition":
        return lambda: condition(item, pid)
    return lambda: medication_request(item, pid)
