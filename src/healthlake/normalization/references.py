"""FHIR reference parsing. Never dereferences over the network."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

# (path, element getter key, allowed target types, required)
RefSpec = tuple[str, list[str], bool]

REF_PATHS: dict[str, list[tuple[str, list[str], bool]]] = {
    "Patient": [("managingOrganization", ["Organization"], False)],
    "Encounter": [
        ("subject", ["Patient"], True),
        ("participant[].individual", ["Practitioner", "PractitionerRole", "RelatedPerson"], False),
        ("serviceProvider", ["Organization"], False),
    ],
    "Condition": [("subject", ["Patient"], True), ("encounter", ["Encounter"], False)],
    "Observation": [("subject", ["Patient"], True), ("encounter", ["Encounter"], False)],
    "MedicationRequest": [
        ("subject", ["Patient"], True),
        ("encounter", ["Encounter"], False),
        (
            "requester",
            ["Practitioner", "PractitionerRole", "Organization", "Patient", "RelatedPerson", "Device"],
            False,
        ),
        ("medicationReference", ["Medication"], False),
    ],
}


@dataclass(frozen=True)
class ParsedRef:
    path: str
    raw: str
    kind: str  # urn_uuid | relative | absolute | contained | identifier | external | invalid
    target_type: str | None
    target_id: str | None = None
    system: str | None = None
    value: str | None = None


def iter_refs(rtype: str, res: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any], list[str], bool]]:
    for path, types, required in REF_PATHS.get(rtype, []):
        if path == "participant[].individual":
            for i, p in enumerate(res.get("participant") or []):
                if isinstance(p, dict) and isinstance(p.get("individual"), dict):
                    yield f"participant[{i}].individual", p["individual"], types, required
            continue
        val = res.get(path)
        if isinstance(val, dict):
            yield path, val, types, required
        elif required:
            yield path, {}, types, required


def parse_reference(path: str, ref: dict[str, Any], fhir_base_url: str | None) -> ParsedRef:
    r = ref.get("reference")
    declared_type = ref.get("type") if isinstance(ref.get("type"), str) else None
    if isinstance(r, str) and r:
        if r.startswith("urn:uuid:"):
            return ParsedRef(path, r, "urn_uuid", declared_type, r)
        if r.startswith("#"):
            return ParsedRef(path, r, "contained", declared_type, r[1:])
        if "?identifier=" in r:
            t, _, q = r.partition("?identifier=")
            system, sep, value = q.partition("|")
            if not sep or not value or "/" in t:
                return ParsedRef(path, r, "invalid", None)
            return ParsedRef(path, r, "identifier", t, None, system, value)
        if r.startswith(("http://", "https://")):
            if fhir_base_url and r.startswith(fhir_base_url):
                rel = r[len(fhir_base_url) :]
                parts = rel.split("/")
                if len(parts) in (2, 4) and parts[0] and parts[1]:
                    return ParsedRef(path, r, "absolute", parts[0], parts[1])
            return ParsedRef(path, r, "external", None)
        parts = r.split("/")
        if len(parts) in (2, 4) and parts[0][:1].isupper() and parts[1]:
            if len(parts) == 4 and parts[2] != "_history":
                return ParsedRef(path, r, "invalid", None)
            return ParsedRef(path, r, "relative", parts[0], parts[1])
        return ParsedRef(path, r, "invalid", None)
    ident = ref.get("identifier")
    if isinstance(ident, dict) and ident.get("system") and ident.get("value"):
        raw = f"{declared_type or '?'}?identifier={ident['system']}|{ident['value']}"
        return ParsedRef(path, raw, "identifier", declared_type, None, str(ident["system"]), str(ident["value"]))
    return ParsedRef(path, "", "missing", None)
