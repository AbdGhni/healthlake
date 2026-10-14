"""FHIR R4 Bundle files (Synthea transaction/batch bundles) -> resource occurrences."""

from __future__ import annotations

import json
from collections.abc import Iterator

from healthlake.adapters.base import AdaptedResource, Issue


def adapt_bundle_file(file_sha256: str, path: str, data: bytes) -> Iterator[AdaptedResource | Issue]:
    try:
        bundle = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        yield Issue("format.json", "fatal", "json_unparseable", f"{path}: {exc}", path, file_sha256)
        return
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        yield Issue("format.fhir_bundle", "fatal", "not_a_bundle", f"{path}: not a FHIR Bundle", path, file_sha256)
        return
    if bundle.get("type") not in ("transaction", "batch", "collection", "searchset"):
        yield Issue(
            "format.fhir_bundle",
            "fatal",
            "bundle_type",
            f"{path}: unsupported Bundle.type",
            path,
            file_sha256,
        )
        return
    for i, entry in enumerate(bundle.get("entry") or []):
        loc = f"{path}#/entry/{i}/resource"
        res = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(res, dict) or not isinstance(res.get("resourceType"), str):
            yield AdaptedResource(
                file_sha256,
                loc,
                "Unknown",
                None,
                {},
                None,
                [
                    Issue(
                        "fhir.structure",
                        "error",
                        "entry_without_resource",
                        "entry has no resource",
                        loc,
                        file_sha256,
                    )
                ],
            )
            continue
        full_url = entry.get("fullUrl")
        rid = res.get("id")
        if not rid and isinstance(full_url, str) and full_url.startswith("urn:uuid:"):
            rid = full_url[len("urn:uuid:") :]
        yield AdaptedResource(
            file_sha256,
            loc,
            res["resourceType"],
            rid if isinstance(rid, str) else None,
            res,
            full_url if isinstance(full_url, str) else None,
        )
