"""Write a finalized batch: data files first, manifest last, then atomic rename of the directory."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from healthlake.errors import ConflictError
from healthlake.ingestion.manifest import MANIFEST_NAME, parse_manifest

MIME_BY_SUFFIX = {".json": "application/json", ".csv": "text/csv"}


def batch_dir_name(revision: int) -> str:
    return f"rev-{revision:06d}"


def write_batch(
    landing: Path,
    source_id: str,
    source_revision: int,
    source_format: str,
    schema_version: str,
    reference_date: str,
    generator: dict[str, Any],
    files: dict[str, bytes],
    mime_overrides: dict[str, str] | None = None,
) -> tuple[Path, str]:
    """Write files + manifest under landing/<source_id>/.tmp-rev-N then rename to rev-N.

    Returns (final_dir, batch_id). If rev-N exists with identical content, it is reused; if it
    exists with different content, ConflictError (a revision is immutable).
    """
    mime_overrides = mime_overrides or {}
    entries = []
    for rel in sorted(files):
        data = files[rel]
        mime = mime_overrides.get(rel) or MIME_BY_SUFFIX[Path(rel).suffix]
        entries.append(
            {
                "path": rel,
                "mime_type": mime,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "manifest_version": 1,
        "source_id": source_id,
        "source_revision": source_revision,
        "source_format": source_format,
        "schema_version": schema_version,
        "synthetic": True,
        "reference_date": reference_date,
        "generator": generator,
        "files": entries,
    }
    raw = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    _, _, bid = parse_manifest(raw)
    source_dir = landing / source_id
    final = source_dir / batch_dir_name(source_revision)
    if final.exists():
        existing = (final / MANIFEST_NAME).read_bytes()
        _, _, existing_id = parse_manifest(existing)
        if existing_id != bid:
            raise ConflictError(
                f"{source_id} revision {source_revision} already exists with different content",
                code="revision_conflict",
            )
        return final, bid
    tmp = source_dir / f".tmp-{batch_dir_name(source_revision)}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for rel, data in files.items():
        target = tmp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    with (tmp / MANIFEST_NAME).open("wb") as f:  # manifest is written last
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, final)
    return final, bid
