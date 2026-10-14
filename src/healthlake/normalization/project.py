"""Step normalize: build Silver rows (versions, provenance, references, codings, projections).

Output: one NDJSON file per target table, each line a JSON array in TABLES column order.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg

from healthlake.errors import HealthLakeError
from healthlake.fhirtypes import parse_date, parse_datetime
from healthlake.ids import MAPPING_VERSION, resource_version_id
from healthlake.ingestion.registry import processing_row, set_processing_status, status_at_least
from healthlake.observability import log_event
from healthlake.pipelines.workspace import Workspace

TABLES: dict[str, list[str]] = {
    "bronze.resource_occurrence": [
        "processing_id",
        "occurrence_no",
        "file_sha256",
        "locator",
        "resource_type",
        "source_resource_id",
        "resource_sha256",
        "entity_id",
        "resource_version_id",
        "outcome",
    ],
    "silver.resource_version": [
        "resource_version_id",
        "entity_id",
        "source_id",
        "resource_type",
        "source_resource_id",
        "first_source_revision",
        "resource_sha256",
        "mapping_version",
        "meta_version_id",
        "in_analytic_scope",
        "resource",
        "first_processing_id",
    ],
    "silver.resource_lineage": ["resource_version_id", "processing_id", "occurrence_no"],
    "silver.processing_resource": ["processing_id", "entity_id", "resource_version_id", "source_revision"],
    "silver.identifier": [
        "resource_version_id",
        "ordinal",
        "entity_id",
        "source_id",
        "resource_type",
        "system",
        "value",
    ],
    "silver.reference": [
        "resource_version_id",
        "path",
        "raw_reference",
        "resolution_method",
        "target_type",
        "target_entity_id",
    ],
    "silver.coding": [
        "resource_version_id",
        "path",
        "ordinal",
        "system",
        "version",
        "code",
        "display",
        "user_selected",
    ],
    "silver.patient": [
        "resource_version_id",
        "entity_id",
        "source_id",
        "gender",
        "birth_date_raw",
        "birth_date_precision",
        "birth_date",
        "deceased",
        "deceased_at",
        "managing_organization_entity_id",
    ],
    "silver.organization": [
        "resource_version_id",
        "entity_id",
        "source_id",
        "name",
        "org_type_code",
        "active",
    ],
    "silver.practitioner": ["resource_version_id", "entity_id", "source_id", "gender", "active"],
    "silver.encounter": [
        "resource_version_id",
        "entity_id",
        "source_id",
        "patient_entity_id",
        "service_provider_entity_id",
        "status",
        "class_code",
        "type_system",
        "type_code",
        "period_start_raw",
        "period_start",
        "period_end_raw",
        "period_end",
    ],
    "silver.encounter_participant": ["resource_version_id", "ordinal", "practitioner_entity_id", "type_code"],
    "silver.condition": [
        "resource_version_id",
        "entity_id",
        "source_id",
        "patient_entity_id",
        "encounter_entity_id",
        "clinical_status",
        "verification_status",
        "category_code",
        "code_system",
        "code",
        "code_display",
        "onset_raw",
        "onset_precision",
        "onset_at",
        "abatement_raw",
        "abatement_at",
        "recorded_raw",
        "recorded_at",
    ],
    "silver.observation": [
        "resource_version_id",
        "entity_id",
        "source_id",
        "patient_entity_id",
        "encounter_entity_id",
        "status",
        "category_code",
        "code_system",
        "code",
        "code_display",
        "effective_raw",
        "effective_precision",
        "effective_at",
        "value_type",
        "value_numeric",
        "value_unit",
        "value_unit_system",
        "value_unit_code",
        "value_string",
        "value_boolean",
        "value_code_system",
        "value_code",
        "value_code_display",
        "value_datetime_raw",
        "value_datetime",
        "data_absent_reason",
        "component_count",
    ],
    "silver.observation_component": [
        "resource_version_id",
        "ordinal",
        "code_system",
        "code",
        "code_display",
        "value_type",
        "value_numeric",
        "value_unit",
        "value_unit_code",
        "value_string",
        "value_boolean",
        "value_code_system",
        "value_code",
        "data_absent_reason",
    ],
    "silver.medication_request": [
        "resource_version_id",
        "entity_id",
        "source_id",
        "patient_entity_id",
        "encounter_entity_id",
        "requester_entity_id",
        "status",
        "intent",
        "medication_system",
        "medication_code",
        "medication_display",
        "authored_raw",
        "authored_at",
    ],
}


def _first_coding(cc: Any) -> tuple[str | None, str | None, str | None]:
    if isinstance(cc, dict):
        for c in cc.get("coding") or []:
            if isinstance(c, dict) and c.get("code"):
                return c.get("system"), c.get("code"), c.get("display") or cc.get("text")
    return None, None, None


def _first(lst: Any) -> Any:
    return lst[0] if isinstance(lst, list) and lst else None


def _time(raw: Any) -> tuple[str | None, str | None, str | None]:
    """(raw, precision, utc instant iso) — instant only when the source carries a time."""
    if not isinstance(raw, str):
        return None, None, None
    pt = parse_datetime(raw)
    if pt is None:
        return raw, None, None
    return raw, pt.precision, pt.instant.isoformat() if pt.instant else None


def _num(v: Any) -> str | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return repr(v) if isinstance(v, float) else str(v)


def _value_fields(el: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"value_type": "none"}
    if "valueQuantity" in el:
        q = el["valueQuantity"]
        out.update(
            value_type="Quantity",
            value_numeric=_num(q.get("value")),
            value_unit=q.get("unit"),
            value_unit_system=q.get("system"),
            value_unit_code=q.get("code"),
        )
    elif "valueCodeableConcept" in el:
        s, c, d = _first_coding(el["valueCodeableConcept"])
        out.update(value_type="CodeableConcept", value_code_system=s, value_code=c, value_code_display=d)
    elif "valueString" in el:
        out.update(value_type="string", value_string=el["valueString"])
    elif "valueBoolean" in el:
        out.update(value_type="boolean", value_boolean=el["valueBoolean"])
    elif "valueInteger" in el:
        out.update(value_type="integer", value_numeric=_num(el["valueInteger"]))
    elif "valueDateTime" in el:
        raw, _, inst = _time(el["valueDateTime"])
        out.update(value_type="dateTime", value_datetime_raw=raw, value_datetime=inst)
    elif "valueTime" in el:
        out.update(value_type="time", value_string=el["valueTime"])
    elif "valuePeriod" in el:
        out.update(value_type="Period", value_string=json.dumps(el["valuePeriod"], sort_keys=True))
    _, dar, _ = _first_coding(el.get("dataAbsentReason"))
    out["data_absent_reason"] = dar
    return out


CODING_PATHS = (
    "code",
    "class",
    "type",
    "category",
    "clinicalStatus",
    "verificationStatus",
    "valueCodeableConcept",
    "medicationCodeableConcept",
    "dataAbsentReason",
    "intent_dummy",
)


def _codings(res: dict[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    out: list[tuple[str, int, dict[str, Any]]] = []

    def add(path: str, cc: Any) -> None:
        if isinstance(cc, dict) and "coding" not in cc and "code" in cc:  # a bare Coding (Encounter.class)
            out.append((path, 0, cc))
            return
        if isinstance(cc, dict):
            for i, c in enumerate(cc.get("coding") or []):
                if isinstance(c, dict):
                    out.append((path, i, c))

    for key in CODING_PATHS:
        val = res.get(key)
        if isinstance(val, list):
            for j, item in enumerate(val):
                add(f"{key}[{j}]", item)
        elif val is not None:
            add(key, val)
    for k, comp in enumerate(res.get("component") or []):
        if isinstance(comp, dict):
            add(f"component[{k}].code", comp.get("code"))
            add(f"component[{k}].valueCodeableConcept", comp.get("valueCodeableConcept"))
    return out


class Writers:
    def __init__(self, ws: Workspace) -> None:
        self.w = {t: ws.ndjson_writer(f"norm_{t}.ndjson") for t in TABLES}

    def row(self, table: str, values: dict[str, Any]) -> None:
        self.w[table].write([values.get(c) for c in TABLES[table]])

    def commit(self) -> dict[str, int]:
        for w in self.w.values():
            w.commit()
        return {t: w.count for t, w in self.w.items()}


def normalize(conn: psycopg.Connection, pid: str, ws: Workspace) -> dict[str, Any]:
    p = processing_row(conn, pid)
    if p["status"] == "blocked":
        raise HealthLakeError("processing is blocked", code="processing_blocked")
    if not status_at_least(p["status"], "validated"):
        raise HealthLakeError("classify must accept the processing first", code="wrong_state")
    done = ws.done("normalize")
    if done is not None:
        if not status_at_least(p["status"], "normalized"):
            with conn.transaction():
                set_processing_status(conn, pid, "normalized")
        return {**done, "idempotent": True}
    source_id, revision = p["source_id"], p["source_revision"]
    decisions = {d["n"]: d for d in ws.ndjson("decisions.ndjson")}
    # Medication codes available in this processing (for MedicationRequest.medicationReference)
    med_codes: dict[str, tuple[str | None, str | None, str | None]] = {}
    for rec in ws.ndjson("adapted.ndjson"):
        d = decisions[rec["n"]]
        if rec["type"] == "Medication" and d["outcome"] in ("out_of_scope", "deduplicated") and d["entity_id"]:
            med_codes[d["entity_id"]] = _first_coding(rec["resource"].get("code"))
    rv_by_entity: dict[str, str] = {}
    w = Writers(ws)
    try:
        for rec in ws.ndjson("adapted.ndjson"):
            d = decisions[rec["n"]]
            res = rec["resource"]
            rv: str | None = None
            if d["outcome"] != "rejected":
                rv = rv_by_entity.get(d["entity_id"]) or resource_version_id(uuid.UUID(d["entity_id"]), d["sha"])
            w.row(
                "bronze.resource_occurrence",
                {
                    "processing_id": pid,
                    "occurrence_no": rec["n"],
                    "file_sha256": rec["file"],
                    "locator": rec["loc"],
                    "resource_type": rec["type"],
                    "source_resource_id": rec["id"],
                    "resource_sha256": d["sha"] or "",
                    "entity_id": d["entity_id"],
                    "resource_version_id": rv,
                    "outcome": d["outcome"],
                },
            )
            if rv is None:
                continue
            w.row(
                "silver.resource_lineage",
                {"resource_version_id": rv, "processing_id": pid, "occurrence_no": rec["n"]},
            )
            if d["outcome"] == "deduplicated":
                continue
            ent = d["entity_id"]
            rv_by_entity[ent] = rv
            meta = res.get("meta") if isinstance(res.get("meta"), dict) else {}
            w.row(
                "silver.resource_version",
                {
                    "resource_version_id": rv,
                    "entity_id": ent,
                    "source_id": source_id,
                    "resource_type": rec["type"],
                    "source_resource_id": rec["id"],
                    "first_source_revision": revision,
                    "resource_sha256": d["sha"],
                    "mapping_version": MAPPING_VERSION,
                    "meta_version_id": (meta or {}).get("versionId"),
                    "in_analytic_scope": d["outcome"] == "accepted",
                    "resource": json.dumps(res, ensure_ascii=False, sort_keys=True),
                    "first_processing_id": pid,
                },
            )
            w.row(
                "silver.processing_resource",
                {
                    "processing_id": pid,
                    "entity_id": ent,
                    "resource_version_id": rv,
                    "source_revision": revision,
                },
            )
            for i, (system, value) in enumerate(d["identifiers"]):
                w.row(
                    "silver.identifier",
                    {
                        "resource_version_id": rv,
                        "ordinal": i,
                        "entity_id": ent,
                        "source_id": source_id,
                        "resource_type": rec["type"],
                        "system": system,
                        "value": value,
                    },
                )
            if d["outcome"] != "accepted":
                continue
            refs = {r["path"]: r for r in d["refs"]}
            for r in d["refs"]:
                w.row(
                    "silver.reference",
                    {
                        "resource_version_id": rv,
                        "path": r["path"],
                        "raw_reference": r["raw"],
                        "resolution_method": r["method"],
                        "target_type": r["target_type"],
                        "target_entity_id": r["target_entity_id"],
                    },
                )
            for path, ordinal, c in _codings(res):
                w.row(
                    "silver.coding",
                    {
                        "resource_version_id": rv,
                        "path": path,
                        "ordinal": ordinal,
                        "system": c.get("system"),
                        "version": c.get("version"),
                        "code": c.get("code"),
                        "display": c.get("display"),
                        "user_selected": c.get("userSelected"),
                    },
                )
            _project(w, rec["type"], res, rv, ent, source_id, refs, med_codes)
    except BaseException:
        for writer in w.w.values():
            writer.f.close()
            writer.tmp.unlink(missing_ok=True)
        raise
    counts = w.commit()
    ws.mark_done("normalize", {"rows": counts})
    with conn.transaction():
        set_processing_status(conn, pid, "normalized")
        log_event("normalized", conn=conn, processing_id=pid, payload={"rows": counts})
    return {"processing_id": pid, "rows": counts}


def _tgt(refs: dict[str, dict[str, Any]], path: str, want: str | None = None) -> str | None:
    r = refs.get(path)
    if r is None or (want and r["target_type"] != want):
        return None
    target: str | None = r["target_entity_id"]
    return target


def _project(
    w: Writers,
    rtype: str,
    res: dict[str, Any],
    rv: str,
    ent: str,
    source_id: str,
    refs: dict[str, dict[str, Any]],
    med_codes: dict[str, tuple[str | None, str | None, str | None]],
) -> None:
    base = {"resource_version_id": rv, "entity_id": ent, "source_id": source_id}
    if rtype == "Patient":
        raw = res.get("birthDate")
        pt = parse_date(raw) if isinstance(raw, str) else None
        dec_raw, _, dec_at = _time(res.get("deceasedDateTime"))
        deceased = res.get("deceasedBoolean") if "deceasedBoolean" in res else (True if dec_raw else None)
        w.row(
            "silver.patient",
            {
                **base,
                "gender": res.get("gender"),
                "birth_date_raw": raw,
                "birth_date_precision": pt.precision if pt else None,
                "birth_date": pt.day.isoformat() if pt and pt.day else None,
                "deceased": deceased,
                "deceased_at": dec_at,
                "managing_organization_entity_id": _tgt(refs, "managingOrganization"),
            },
        )
    elif rtype == "Organization":
        w.row(
            "silver.organization",
            {
                **base,
                "name": res.get("name"),
                "org_type_code": _first_coding(_first(res.get("type")))[1],
                "active": res.get("active"),
            },
        )
    elif rtype == "Practitioner":
        w.row("silver.practitioner", {**base, "gender": res.get("gender"), "active": res.get("active")})
    elif rtype == "Encounter":
        period = res.get("period") or {}
        s_raw, _, s_at = _time(period.get("start"))
        e_raw, _, e_at = _time(period.get("end"))
        ts, tc, _ = _first_coding(_first(res.get("type")))
        w.row(
            "silver.encounter",
            {
                **base,
                "patient_entity_id": _tgt(refs, "subject"),
                "service_provider_entity_id": _tgt(refs, "serviceProvider"),
                "status": res.get("status"),
                "class_code": (res.get("class") or {}).get("code"),
                "type_system": ts,
                "type_code": tc,
                "period_start_raw": s_raw,
                "period_start": s_at,
                "period_end_raw": e_raw,
                "period_end": e_at,
            },
        )
        for i, part in enumerate(res.get("participant") or []):
            pe = _tgt(refs, f"participant[{i}].individual", "Practitioner")
            if pe:
                w.row(
                    "silver.encounter_participant",
                    {
                        "resource_version_id": rv,
                        "ordinal": i,
                        "practitioner_entity_id": pe,
                        "type_code": _first_coding(_first(part.get("type")))[1],
                    },
                )
    elif rtype == "Condition":
        cs, cc, cd = _first_coding(res.get("code"))
        o_raw, o_prec, o_at = _time(res.get("onsetDateTime"))
        a_raw, _, a_at = _time(res.get("abatementDateTime"))
        r_raw, _, r_at = _time(res.get("recordedDate"))
        w.row(
            "silver.condition",
            {
                **base,
                "patient_entity_id": _tgt(refs, "subject"),
                "encounter_entity_id": _tgt(refs, "encounter"),
                "clinical_status": _first_coding(res.get("clinicalStatus"))[1],
                "verification_status": _first_coding(res.get("verificationStatus"))[1],
                "category_code": _first_coding(_first(res.get("category")))[1],
                "code_system": cs,
                "code": cc,
                "code_display": cd,
                "onset_raw": o_raw,
                "onset_precision": o_prec,
                "onset_at": o_at,
                "abatement_raw": a_raw,
                "abatement_at": a_at,
                "recorded_raw": r_raw,
                "recorded_at": r_at,
            },
        )
    elif rtype == "Observation":
        cs, cc, cd = _first_coding(res.get("code"))
        eff = (
            res.get("effectiveDateTime")
            or res.get("effectiveInstant")
            or (res.get("effectivePeriod") or {}).get("start")
        )
        e_raw, e_prec, e_at = _time(eff)
        comps = [c for c in res.get("component") or [] if isinstance(c, dict)]
        w.row(
            "silver.observation",
            {
                **base,
                "patient_entity_id": _tgt(refs, "subject"),
                "encounter_entity_id": _tgt(refs, "encounter"),
                "status": res.get("status"),
                "category_code": _first_coding(_first(res.get("category")))[1],
                "code_system": cs,
                "code": cc,
                "code_display": cd,
                "effective_raw": e_raw,
                "effective_precision": e_prec,
                "effective_at": e_at,
                **_value_fields(res),
                "component_count": len(comps),
            },
        )
        for i, comp in enumerate(comps):
            ccs, ccc, ccd = _first_coding(comp.get("code"))
            v = _value_fields(comp)
            w.row(
                "silver.observation_component",
                {
                    "resource_version_id": rv,
                    "ordinal": i,
                    "code_system": ccs,
                    "code": ccc,
                    "code_display": ccd,
                    **v,
                },
            )
    elif rtype == "MedicationRequest":
        ms, mc, md = _first_coding(res.get("medicationCodeableConcept"))
        if mc is None:
            target = _tgt(refs, "medicationReference")
            if target and target in med_codes:
                ms, mc, md = med_codes[target]
            elif (res.get("medicationReference") or {}).get("reference", "").startswith("#"):
                cid = res["medicationReference"]["reference"][1:]
                for c in res.get("contained") or []:
                    if isinstance(c, dict) and c.get("id") == cid:
                        ms, mc, md = _first_coding(c.get("code"))
        a_raw, _, a_at = _time(res.get("authoredOn"))
        w.row(
            "silver.medication_request",
            {
                **base,
                "patient_entity_id": _tgt(refs, "subject"),
                "encounter_entity_id": _tgt(refs, "encounter"),
                "requester_entity_id": _tgt(refs, "requester", "Practitioner"),
                "status": res.get("status"),
                "intent": res.get("intent"),
                "medication_system": ms,
                "medication_code": mc,
                "medication_display": md,
                "authored_raw": a_raw,
                "authored_at": a_at,
            },
        )
