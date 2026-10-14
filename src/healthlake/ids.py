"""Content identifiers and canonical JSON.

Canonical JSON used for hashing (HealthLake convention, not RFC 8785/JCS):
  json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
  encoded as UTF-8. Numbers are serialised by Python's json module as parsed (floats keep repr()).
Identifiers never contain operational timestamps.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from typing import Any

CODE_VERSION = "0.1.0"
MAPPING_VERSION = "map-1"
VALIDATION_VERSION = "val-1"

# Root namespace for source namespaces: uuid5(NAMESPACE_URL, "urn:healthlake")
HEALTHLAKE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:healthlake")


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_bytes(canonical_json(obj))


def source_namespace(source_id: str) -> uuid.UUID:
    return uuid.uuid5(HEALTHLAKE_NAMESPACE, f"source:{source_id}")


def entity_id(source_id: str, resource_type: str, source_resource_id: str) -> uuid.UUID:
    return uuid.uuid5(source_namespace(source_id), f"{resource_type}/{source_resource_id}")


def batch_id(manifest: dict[str, Any]) -> str:
    return sha256_json(manifest)


def processing_id(
    batch: str,
    code_version: str = CODE_VERSION,
    mapping_version: str = MAPPING_VERSION,
    validation_version: str = VALIDATION_VERSION,
) -> str:
    return sha256_json(
        {
            "batch_id": batch,
            "code": code_version,
            "mapping": mapping_version,
            "validation": validation_version,
        }
    )


def resource_version_id(entity: uuid.UUID, resource_sha256: str, mapping_version: str = MAPPING_VERSION) -> str:
    return sha256_json({"entity_id": str(entity), "resource_sha256": resource_sha256, "mapping": mapping_version})


def release_id(processing_ids: Iterable[str], code_version: str = CODE_VERSION, build: str = "") -> str:
    """build: fingerprint of the Gold build (dbt project content and build options)."""
    return sha256_json({"processings": sorted(set(processing_ids)), "code": code_version, "build": build})


def release_schema(release: str) -> str:
    if len(release) != 64 or any(c not in "0123456789abcdef" for c in release):
        raise ValueError("release_id must be 64 lowercase hex characters")
    return f"release_{release[:16]}"
