"""Deterministic derivation of the Horizon business formats from Synthea FHIR output.

These formats are HealthLake's own fictional business exports (horizon-csv-v1, horizon-json-v1).
They are not Synthea formats. Only analytic resource types are exported, as a business system would.
Names, addresses and telecom are deliberately not exported.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

NPI = "http://hl7.org/fhir/sid/us-npi"
SYNTHEA_ID = "https://github.com/synthetichealth/synthea"

CSV_COLUMNS: dict[str, list[str]] = {
    "organizations.csv": ["organization_id", "name", "type_code", "active"],
    "practitioners.csv": ["practitioner_id", "npi", "gender", "active"],
    "patients.csv": ["patient_id", "gender", "birth_date", "deceased_datetime", "managing_organization_id"],
    "encounters.csv": [
        "encounter_id",
        "patient_id",
        "organization_id",
        "practitioner_npi",
        "status",
        "class_code",
        "type_system",
        "type_code",
        "type_display",
        "start",
        "end",
    ],
    "conditions.csv": [
        "condition_id",
        "patient_id",
        "encounter_id",
        "clinical_status",
        "verification_status",
        "category",
        "code_system",
        "code",
        "display",
        "onset",
        "abatement",
        "recorded",
    ],
    "observations.csv": [
        "observation_id",
        "patient_id",
        "encounter_id",
        "status",
        "category",
        "code_system",
        "code",
        "display",
        "effective",
        "value_type",
        "value",
        "unit",
        "unit_code",
        "value_code_system",
        "value_code",
        "value_code_display",
        "data_absent_reason",
    ],
    "observation_components.csv": [
        "observation_id",
        "ordinal",
        "code_system",
        "code",
        "display",
        "value_type",
        "value",
        "unit",
        "unit_code",
        "value_code_system",
        "value_code",
        "data_absent_reason",
    ],
    "medication_requests.csv": [
        "medication_request_id",
        "patient_id",
        "encounter_id",
        "requester_npi",
        "status",
        "intent",
        "medication_system",
        "medication_code",
        "medication_display",
        "authored",
    ],
}


def iter_resources(files: dict[str, bytes]) -> Iterator[dict[str, Any]]:
    for name in sorted(files):
        bundle = json.loads(files[name])
        for entry in bundle.get("entry", []):
            yield entry["resource"]


def _coding(cc: dict[str, Any] | None) -> tuple[str, str, str]:
    if not cc:
        return "", "", ""
    codings = cc.get("coding") or [{}]
    c = codings[0]
    return c.get("system", ""), c.get("code", ""), c.get("display", cc.get("text", ""))


def _ref_id(ref: dict[str, Any] | None) -> str:
    if not ref:
        return ""
    r = str(ref.get("reference", ""))
    if r.startswith("urn:uuid:"):
        return r[len("urn:uuid:") :]
    if "?identifier=" in r:
        return r.split("|", 1)[1]
    return r.split("/")[-1]


def _value(o: dict[str, Any]) -> dict[str, str]:
    out = dict.fromkeys(
        ["value_type", "value", "unit", "unit_code", "value_code_system", "value_code", "value_code_display"],
        "",
    )
    out["data_absent_reason"] = _coding(o.get("dataAbsentReason"))[1]
    if "valueQuantity" in o:
        q = o["valueQuantity"]
        out.update(
            value_type="quantity",
            value=repr(q.get("value", "")) if isinstance(q.get("value"), float) else str(q.get("value", "")),
            unit=q.get("unit", ""),
            unit_code=q.get("code", ""),
        )
    elif "valueCodeableConcept" in o:
        s, c, d = _coding(o["valueCodeableConcept"])
        out.update(value_type="coded", value_code_system=s, value_code=c, value_code_display=d)
    elif "valueString" in o:
        out.update(value_type="string", value=o["valueString"])
    elif "valueBoolean" in o:
        out.update(value_type="boolean", value="true" if o["valueBoolean"] else "false")
    elif "valueInteger" in o:
        out.update(value_type="integer", value=str(o["valueInteger"]))
    elif "valueDateTime" in o:
        out.update(value_type="datetime", value=o["valueDateTime"])
    else:
        out["value_type"] = "none"
    return out


def extract_rows(files: dict[str, bytes]) -> dict[str, list[dict[str, str]]]:
    rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    meds: dict[str, tuple[str, str, str]] = {}
    resources = list(iter_resources(files))
    for r in resources:
        if r["resourceType"] == "Medication":
            meds[r["id"]] = _coding(r.get("code"))
    seen: set[tuple[str, str]] = set()
    for r in resources:
        t, rid = r["resourceType"], r["id"]
        if (t, rid) in seen:
            continue
        seen.add((t, rid))
        if t == "Organization":
            rows["organizations.csv"].append(
                {
                    "organization_id": rid,
                    "name": r.get("name", ""),
                    "type_code": _coding((r.get("type") or [None])[0])[1],
                    "active": str(r.get("active", True)).lower(),
                }
            )
        elif t == "Practitioner":
            npi = next((i["value"] for i in r.get("identifier", []) if i.get("system") == NPI), "")
            rows["practitioners.csv"].append(
                {
                    "practitioner_id": rid,
                    "npi": npi,
                    "gender": r.get("gender", ""),
                    "active": str(r.get("active", True)).lower(),
                }
            )
        elif t == "Patient":
            rows["patients.csv"].append(
                {
                    "patient_id": rid,
                    "gender": r.get("gender", ""),
                    "birth_date": r.get("birthDate", ""),
                    "deceased_datetime": r.get("deceasedDateTime", ""),
                    "managing_organization_id": _ref_id(r.get("managingOrganization")),
                }
            )
        elif t == "Encounter":
            s, c, d = _coding((r.get("type") or [None])[0])
            part = next((p.get("individual") for p in r.get("participant", []) if p.get("individual")), None)
            period = r.get("period", {})
            rows["encounters.csv"].append(
                {
                    "encounter_id": rid,
                    "patient_id": _ref_id(r.get("subject")),
                    "organization_id": _ref_id(r.get("serviceProvider")),
                    "practitioner_npi": _ref_id(part),
                    "status": r.get("status", ""),
                    "class_code": r.get("class", {}).get("code", ""),
                    "type_system": s,
                    "type_code": c,
                    "type_display": d,
                    "start": period.get("start", ""),
                    "end": period.get("end", ""),
                }
            )
        elif t == "Condition":
            s, c, d = _coding(r.get("code"))
            rows["conditions.csv"].append(
                {
                    "condition_id": rid,
                    "patient_id": _ref_id(r.get("subject")),
                    "encounter_id": _ref_id(r.get("encounter")),
                    "clinical_status": _coding(r.get("clinicalStatus"))[1],
                    "verification_status": _coding(r.get("verificationStatus"))[1],
                    "category": _coding((r.get("category") or [None])[0])[1],
                    "code_system": s,
                    "code": c,
                    "display": d,
                    "onset": r.get("onsetDateTime", ""),
                    "abatement": r.get("abatementDateTime", ""),
                    "recorded": r.get("recordedDate", ""),
                }
            )
        elif t == "Observation":
            s, c, d = _coding(r.get("code"))
            v = _value(r)
            rows["observations.csv"].append(
                {
                    "observation_id": rid,
                    "patient_id": _ref_id(r.get("subject")),
                    "encounter_id": _ref_id(r.get("encounter")),
                    "status": r.get("status", ""),
                    "category": _coding((r.get("category") or [None])[0])[1],
                    "code_system": s,
                    "code": c,
                    "display": d,
                    "effective": r.get("effectiveDateTime", ""),
                    **v,
                }
            )
            for i, comp in enumerate(r.get("component", [])):
                cs, cc, cd = _coding(comp.get("code"))
                cv = _value(comp)
                cv.pop("value_code_display")
                rows["observation_components.csv"].append(
                    {
                        "observation_id": rid,
                        "ordinal": str(i),
                        "code_system": cs,
                        "code": cc,
                        "display": cd,
                        **cv,
                    }
                )
        elif t == "MedicationRequest":
            if "medicationCodeableConcept" in r:
                ms, mc, md = _coding(r["medicationCodeableConcept"])
            else:
                ms, mc, md = meds.get(_ref_id(r.get("medicationReference")), ("", "", ""))
            rows["medication_requests.csv"].append(
                {
                    "medication_request_id": rid,
                    "patient_id": _ref_id(r.get("subject")),
                    "encounter_id": _ref_id(r.get("encounter")),
                    "requester_npi": _ref_id(r.get("requester")),
                    "status": r.get("status", ""),
                    "intent": r.get("intent", ""),
                    "medication_system": ms,
                    "medication_code": mc,
                    "medication_display": md,
                    "authored": r.get("authoredOn", ""),
                }
            )
    for name, cols in CSV_COLUMNS.items():
        key = cols[0]
        rows[name].sort(key=lambda row: (row[key], row.get("ordinal", "").zfill(4)))
    return rows


def to_csv_files(rows: dict[str, list[dict[str, str]]]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name, cols in CSV_COLUMNS.items():
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows.get(name, []))
        out[name] = buf.getvalue().encode("utf-8")
    return out


def to_json_files(rows: dict[str, list[dict[str, str]]], patients_per_file: int = 50) -> dict[str, bytes]:
    """horizon-json-v1: reference data file + patient record files with nested encounters."""

    def clean(d: dict[str, str]) -> dict[str, str]:
        return {k: v for k, v in d.items() if v != ""}

    out: dict[str, bytes] = {}
    ref = {
        "schema": "horizon-json-v1",
        "organizations": [clean(r) for r in rows["organizations.csv"]],
        "practitioners": [clean(r) for r in rows["practitioners.csv"]],
    }
    out["reference-data.json"] = json.dumps(ref, indent=1, sort_keys=True).encode("utf-8")
    comps: dict[str, list[dict[str, str]]] = defaultdict(list)
    for c in rows["observation_components.csv"]:
        comps[c["observation_id"]].append(clean({k: v for k, v in c.items() if k != "observation_id"}))
    by_enc: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    loose: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for kind, fname in (
        ("observations", "observations.csv"),
        ("conditions", "conditions.csv"),
        ("medication_requests", "medication_requests.csv"),
    ):
        for r in rows[fname]:
            item: dict[str, Any] = clean({k: v for k, v in r.items() if k != "patient_id"})
            if kind == "observations" and r["observation_id"] in comps:
                item["components"] = comps[r["observation_id"]]
            enc = item.pop("encounter_id", None)
            if enc:
                by_enc[enc][kind].append(item)
            else:
                loose[r["patient_id"]][kind].append(item)
    encounters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in rows["encounters.csv"]:
        item = clean({k: v for k, v in e.items() if k != "patient_id"})
        enc_item: dict[str, Any] = dict(item)
        enc_item.update(by_enc.get(e["encounter_id"], {}))
        item = enc_item
        encounters[e["patient_id"]].append(item)
    patients = []
    for p in rows["patients.csv"]:
        rec: dict[str, Any] = clean(p)
        rec["encounters"] = encounters.get(p["patient_id"], [])
        rec.update(loose.get(p["patient_id"], {}))
        patients.append(rec)
    for i in range(0, max(len(patients), 1), patients_per_file):
        chunk = patients[i : i + patients_per_file]
        doc = {"schema": "horizon-json-v1", "patients": chunk}
        out[f"records/records-{i // patients_per_file + 1:04d}.json"] = json.dumps(
            doc, indent=1, sort_keys=True
        ).encode("utf-8")
    return out
