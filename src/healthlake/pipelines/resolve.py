"""Step resolve: identities, references, dependency propagation, deduplication and conflicts.

Outcome per occurrence (disjoint): rejected > deduplicated > out_of_scope > accepted.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import psycopg

from healthlake.ids import entity_id, sha256_json
from healthlake.ingestion.registry import processing_row
from healthlake.normalization.references import ParsedRef, iter_refs, parse_reference
from healthlake.observability import log_event
from healthlake.pipelines.adapt_validate import _require
from healthlake.pipelines.workspace import Workspace
from healthlake.validation.structural import PROJECTED

LEVEL = {
    "Organization": 0,
    "Practitioner": 0,
    "Patient": 1,
    "Encounter": 2,
    "Condition": 3,
    "Observation": 3,
    "MedicationRequest": 3,
}


@dataclass
class Rec:
    n: int
    rtype: str
    sid: str | None
    entity: uuid.UUID | None
    rhash: str
    loc: str
    file: str
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    refs: list[tuple[str, dict[str, Any], list[str], bool]] = field(default_factory=list)
    contained: set[str] = field(default_factory=set)
    identifiers: list[tuple[str, str]] = field(default_factory=list)
    resolved: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = ""
    caused_by: int | None = None


def _issue(rec: Rec, check: str, cause: str, msg: str, severity: str = "error") -> dict[str, Any]:
    return {
        "check_id": check,
        "severity": severity,
        "cause_code": cause,
        "message": msg,
        "locator": rec.loc,
        "file_sha256": rec.file,
    }


def resolve(conn: psycopg.Connection, pid: str, ws: Workspace, sources_cfg: dict[str, Any]) -> dict[str, Any]:
    p = processing_row(conn, pid)
    _require(p, "adapted")
    done = ws.done("resolve")
    if done is not None:
        return {**done, "idempotent": True}
    if ws.done("validate") is None:
        from healthlake.errors import HealthLakeError

        raise HealthLakeError("validate must run before resolve", code="wrong_state")
    source_id: str = p["source_id"]
    src_cfg = next(s for s in sources_cfg["sources"] if s["source_id"] == source_id)
    base_url = src_cfg.get("fhir_base_url")
    identity_systems: dict[str, list[str]] = sources_cfg.get("identity_systems", {})

    vissues: dict[int, list[dict[str, Any]]] = {r["n"]: r["issues"] for r in ws.ndjson("validation.ndjson")}

    # ---- pass 1: index -------------------------------------------------------------------------
    recs: list[Rec] = []
    by_full_url: dict[str, tuple[str, uuid.UUID]] = {}
    present: dict[uuid.UUID, str] = {}
    ident_index: dict[tuple[str, str, str], set[uuid.UUID]] = defaultdict(set)
    for raw in ws.ndjson("adapted.ndjson"):
        res = raw["resource"]
        rtype, sid = raw["type"], raw["id"]
        ent = entity_id(source_id, rtype, sid) if sid else None
        rec = Rec(raw["n"], rtype, sid, ent, sha256_json(res) if res else "", raw["loc"], raw["file"])
        for i in vissues.get(rec.n, []):
            (rec.errors if i["severity"] in ("error", "fatal") else rec.warnings).append(i)
        if ent is None and not rec.errors:
            rec.errors.append(_issue(rec, "fhir.id", "missing_id", "resource has no id"))
        if ent is not None:
            present.setdefault(ent, rtype)
            if raw.get("full_url"):
                by_full_url[raw["full_url"]] = (rtype, ent)
            for ident in res.get("identifier") or []:
                if isinstance(ident, dict) and ident.get("system") and ident.get("value"):
                    key = (rtype, str(ident["system"]), str(ident["value"]))
                    ident_index[key].add(ent)
                    rec.identifiers.append((key[1], key[2]))
        if rtype in PROJECTED and res:
            rec.refs = list(iter_refs(rtype, res))
            rec.contained = {str(c["id"]) for c in res.get("contained") or [] if isinstance(c, dict) and c.get("id")}
        recs.append(rec)

    # ---- Silver lookups for targets outside this processing ------------------------------------
    parsed: dict[int, list[tuple[ParsedRef, list[str], bool]]] = {}
    want_entities: set[uuid.UUID] = set()
    want_idents: set[tuple[str, str, str]] = set()
    for rec in recs:
        if not rec.refs:
            continue
        lst = []
        for path, ref, types, required in rec.refs:
            pr = parse_reference(path, ref, base_url)
            lst.append((pr, types, required))
            if pr.kind in ("relative", "absolute") and pr.target_type and pr.target_id:
                e = entity_id(source_id, pr.target_type, pr.target_id)
                if e not in present:
                    want_entities.add(e)
            elif pr.kind == "identifier":
                for t in [pr.target_type] if pr.target_type else types:
                    want_idents.add((t, pr.system or "", pr.value or ""))
        parsed[rec.n] = lst
    existing_all = _silver_entities(conn, [r.entity for r in recs if r.entity] + list(want_entities))
    silver_idents = _silver_identifiers(conn, source_id, want_idents | set(ident_index))
    enc_patient = {}
    for rec in recs:
        if rec.rtype == "Encounter" and rec.entity:
            for pr, _, _ in parsed.get(rec.n, []):
                if pr.path == "subject":
                    enc_patient[rec.entity] = pr
    silver_enc_patient = _silver_encounter_patients(conn, [e for e in want_entities if e not in present])

    by_n = {r.n: r for r in recs}
    rejected_entities: dict[uuid.UUID, int] = {}
    fatal: list[dict[str, Any]] = []

    # ---- identity conflicts ----------------------------------------------------------------------
    for (rtype, system, value), ents in sorted(ident_index.items(), key=lambda kv: kv[0]):
        if system not in identity_systems.get(rtype, []):
            continue
        claim = set(ents) | silver_idents.get((rtype, system, value), set())
        if len(claim) > 1:
            fatal.append(
                {
                    "check_id": "identity.conflict",
                    "severity": "fatal",
                    "cause_code": "identity_conflict",
                    "message": f"{rtype} identifier {system}|{value} claimed by {len(claim)} identities",
                    "locator": None,
                    "file_sha256": None,
                }
            )

    def resolve_one(rec: Rec, pr: ParsedRef, types: list[str]) -> tuple[str | None, uuid.UUID | None, str | None]:
        """Return (error cause, target entity, target type)."""
        if pr.kind == "missing":
            return "reference_missing", None, None
        if pr.kind in ("invalid", "external"):
            return f"reference_{pr.kind}", None, None
        if pr.kind == "contained":
            if pr.target_id in rec.contained:
                return None, None, pr.target_type or "contained"
            return "contained_not_found", None, None
        if pr.kind == "urn_uuid":
            hit = by_full_url.get(pr.raw)
            if hit is None:
                return "reference_unresolved", None, None
            return (None if hit[0] in types else "wrong_target_type"), hit[1], hit[0]
        if pr.kind in ("relative", "absolute"):
            assert pr.target_type and pr.target_id
            if pr.target_type not in types:
                return "wrong_target_type", None, pr.target_type
            e = entity_id(source_id, pr.target_type, pr.target_id)
            if e in present or e in existing_all:
                return None, e, pr.target_type
            return "reference_unresolved", None, None
        # identifier
        cand_types = [pr.target_type] if pr.target_type else types
        if pr.target_type and pr.target_type not in types:
            return "wrong_target_type", None, pr.target_type
        found: set[tuple[str, uuid.UUID]] = set()
        for t in cand_types:
            key = (t, pr.system or "", pr.value or "")
            found |= {(t, e) for e in ident_index.get(key, set())}
            found |= {(t, e) for e in silver_idents.get(key, set())}
        known = any(pr.system in identity_systems.get(t, []) for t in cand_types)
        if not known:
            return "identifier_system_unknown", None, None
        if len(found) > 1:
            return "reference_ambiguous", None, None
        if not found:
            return "reference_unresolved", None, None
        t, e = next(iter(found))
        return None, e, t

    # ---- level-ordered resolution with dependency propagation ------------------------------------
    for level in (0, 1, 2, 3):
        for rec in recs:
            if LEVEL.get(rec.rtype, 0) != level:
                continue
            if rec.errors:
                rec.outcome = "rejected"
                if rec.entity:
                    rejected_entities.setdefault(rec.entity, rec.n)
                continue
            if rec.rtype not in PROJECTED:
                continue
            subject: uuid.UUID | None = None
            encounter: uuid.UUID | None = None
            for pr, types, required in parsed.get(rec.n, []):
                cause, target, ttype = resolve_one(rec, pr, types)
                if cause:
                    blocking = required or cause in (
                        "reference_ambiguous",
                        "wrong_target_type",
                        "reference_invalid",
                    )
                    issue = _issue(
                        rec,
                        "reference.resolution",
                        cause,
                        f"{pr.path}: {cause} ({pr.raw[:120]})",
                        "error" if blocking else "warning",
                    )
                    (rec.errors if blocking else rec.warnings).append(issue)
                    continue
                if target is not None and target in rejected_entities and target not in existing_all:
                    rec.errors.append(
                        _issue(
                            rec,
                            "reference.dependency",
                            "dependency_rejected",
                            f"{pr.path} points to a rejected resource",
                        )
                    )
                    rec.caused_by = rejected_entities[target]
                    continue
                rec.resolved.append(
                    {
                        "path": pr.path,
                        "raw": pr.raw,
                        "method": _method(pr, by_full_url),
                        "target_type": ttype,
                        "target_entity_id": str(target) if target else None,
                    }
                )
                if pr.path == "subject":
                    subject = target
                if pr.path == "encounter":
                    encounter = target
            if not rec.errors and rec.rtype in ("Condition", "Observation", "MedicationRequest") and encounter:
                enc_subject = _encounter_subject(encounter, enc_patient, by_full_url, source_id, silver_enc_patient)
                if enc_subject is not None and subject is not None and enc_subject != subject:
                    rec.errors.append(
                        _issue(
                            rec,
                            "consistency.patient_encounter",
                            "patient_encounter_mismatch",
                            "subject differs from the patient of the referenced encounter",
                        )
                    )
            if rec.errors:
                rec.outcome = "rejected"
                if rec.entity:
                    rejected_entities.setdefault(rec.entity, rec.n)

    # ---- deduplication, conflicts, outcomes ------------------------------------------------------
    first_by_entity: dict[uuid.UUID, Rec] = {}
    for rec in recs:
        if rec.outcome == "rejected" or rec.entity is None:
            rec.outcome = "rejected"
            continue
        prev = first_by_entity.get(rec.entity)
        if prev is None:
            first_by_entity[rec.entity] = rec
            rec.outcome = "accepted" if rec.rtype in PROJECTED else "out_of_scope"
        elif prev.rhash == rec.rhash:
            rec.outcome = "deduplicated"
        else:
            rec.outcome = "rejected"
            fatal.append(
                {
                    "check_id": "identity.content_conflict",
                    "severity": "fatal",
                    "cause_code": "content_conflict",
                    "message": f"{rec.rtype}/{rec.sid} appears twice with different content in one revision",
                    "locator": rec.loc,
                    "file_sha256": rec.file,
                }
            )
    # an entity with a valid occurrence is not "rejected" for update purposes
    valid_entities = set(first_by_entity)
    invalid_updates = 0
    rejected_new = 0
    received_new = 0
    for rec in recs:
        is_existing = rec.entity is not None and rec.entity in existing_all
        if not is_existing:
            received_new += 1
        if rec.outcome == "rejected" and not any(i["cause_code"] == "content_conflict" for i in rec.errors):
            if is_existing and rec.entity not in valid_entities:
                invalid_updates += 1
                rec.errors.append(
                    _issue(
                        rec,
                        "identity.invalid_update",
                        "invalid_update",
                        "invalid content for an identity already in Silver",
                        "fatal",
                    )
                )
            elif not is_existing:
                rejected_new += 1

    counts: dict[str, int] = defaultdict(int)
    with ws.ndjson_writer("decisions.ndjson") as out:
        for rec in recs:
            counts[rec.outcome] += 1
            out.write(
                {
                    "n": rec.n,
                    "type": rec.rtype,
                    "id": rec.sid,
                    "entity_id": str(rec.entity) if rec.entity else None,
                    "sha": rec.rhash,
                    "outcome": rec.outcome,
                    "refs": rec.resolved,
                    "issues": rec.errors + rec.warnings,
                    "caused_by_n": rec.caused_by,
                    "identifiers": rec.identifiers,
                }
            )
    summary = {
        "received": len(recs),
        "accepted": counts["accepted"],
        "deduplicated": counts["deduplicated"],
        "rejected": counts["rejected"],
        "out_of_scope": counts["out_of_scope"],
        "received_new": received_new,
        "rejected_new": rejected_new,
        "invalid_updates": invalid_updates,
        "fatal_issues": fatal,
    }
    assert summary["received"] == sum(counts[k] for k in ("accepted", "deduplicated", "rejected", "out_of_scope"))
    ws.mark_done("resolve", summary)
    log_event("resolved", processing_id=pid, payload={k: v for k, v in summary.items() if k != "fatal_issues"})
    del by_n
    return {k: v for k, v in summary.items() if k != "fatal_issues"} | {"fatal_issues": len(fatal)}


def _method(pr: ParsedRef, by_full_url: dict[str, Any]) -> str:
    if pr.kind == "urn_uuid":
        return "urn_uuid"
    return pr.kind


def _encounter_subject(
    enc: uuid.UUID,
    enc_patient: dict[uuid.UUID, ParsedRef],
    by_full_url: dict[str, tuple[str, uuid.UUID]],
    source_id: str,
    silver_enc_patient: dict[uuid.UUID, uuid.UUID],
) -> uuid.UUID | None:
    pr = enc_patient.get(enc)
    if pr is None:
        return silver_enc_patient.get(enc)
    if pr.kind == "urn_uuid":
        hit = by_full_url.get(pr.raw)
        return hit[1] if hit else None
    if pr.kind in ("relative", "absolute") and pr.target_type and pr.target_id:
        return entity_id(source_id, pr.target_type, pr.target_id)
    return None


def _silver_entities(conn: psycopg.Connection, ents: list[uuid.UUID]) -> set[uuid.UUID]:
    out: set[uuid.UUID] = set()
    uniq = list(set(ents))
    for i in range(0, len(uniq), 50_000):
        rows = conn.execute(
            "SELECT DISTINCT entity_id FROM silver.processing_resource WHERE entity_id = ANY(%s)",
            (uniq[i : i + 50_000],),
        ).fetchall()
        out |= {r[0] for r in rows}
    return out


def _silver_identifiers(
    conn: psycopg.Connection, source_id: str, keys: set[tuple[str, str, str]]
) -> dict[tuple[str, str, str], set[uuid.UUID]]:
    out: dict[tuple[str, str, str], set[uuid.UUID]] = defaultdict(set)
    ks = sorted(keys)
    for i in range(0, len(ks), 20_000):
        chunk = ks[i : i + 20_000]
        rows = conn.execute(
            "SELECT DISTINCT i.resource_type, i.system, i.value, i.entity_id FROM silver.identifier i"
            " JOIN unnest(%s::text[], %s::text[], %s::text[]) AS k(t, s, v)"
            " ON i.resource_type=k.t AND i.system=k.s AND i.value=k.v WHERE i.source_id=%s",
            ([k[0] for k in chunk], [k[1] for k in chunk], [k[2] for k in chunk], source_id),
        ).fetchall()
        for t, s, v, e in rows:
            out[(t, s, v)].add(e)
    return out


def _silver_encounter_patients(conn: psycopg.Connection, encs: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not encs:
        return {}
    rows = conn.execute(
        "SELECT DISTINCT ON (pr.entity_id) pr.entity_id, e.patient_entity_id FROM silver.processing_resource pr"
        " JOIN silver.encounter e USING (resource_version_id) WHERE pr.entity_id = ANY(%s)"
        " ORDER BY pr.entity_id, pr.source_revision DESC",
        (encs,),
    ).fetchall()
    return {r[0]: r[1] for r in rows}
