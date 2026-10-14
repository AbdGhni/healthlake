"""Adapter output: one AdaptedResource per resource occurrence, plus file-level issues."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NPI = "http://hl7.org/fhir/sid/us-npi"
SYNTHEA_ID = "https://github.com/synthetichealth/synthea"


@dataclass
class Issue:
    check_id: str
    severity: str  # fatal | error | warning | info
    cause_code: str
    message: str
    locator: str | None = None
    file_sha256: str | None = None


@dataclass
class AdaptedResource:
    file_sha256: str
    locator: str
    resource_type: str
    source_resource_id: str | None
    resource: dict[str, Any]
    full_url: str | None = None
    issues: list[Issue] = field(default_factory=list)

    def to_record(self, n: int) -> dict[str, Any]:
        return {
            "n": n,
            "file": self.file_sha256,
            "loc": self.locator,
            "type": self.resource_type,
            "id": self.source_resource_id,
            "full_url": self.full_url,
            "resource": self.resource,
            "issues": [vars(i) for i in self.issues],
        }


def ref(resource_type: str, rid: str | None) -> dict[str, str] | None:
    return {"reference": f"{resource_type}/{rid}"} if rid else None


def ident_ref(resource_type: str, system: str, value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    return {"type": resource_type, "identifier": {"system": system, "value": value}}


def cc(system: str | None, code: str | None, display: str | None = None) -> dict[str, Any] | None:
    if not code:
        return None
    coding: dict[str, str] = {"code": code}
    if system:
        coding["system"] = system
    if display:
        coding["display"] = display
    return {"coding": [coding], **({"text": display} if display else {})}


def prune(d: dict[str, Any]) -> dict[str, Any]:
    """Drop None/empty values (FHIR forbids empty elements)."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        out[k] = v
    return out
