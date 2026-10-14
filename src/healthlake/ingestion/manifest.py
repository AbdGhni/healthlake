"""Batch manifest contract (manifest_version 1)."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from healthlake.errors import ContractError
from healthlake.ids import batch_id as compute_batch_id

MANIFEST_NAME = "manifest.json"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_MIME = {"application/fhir+json", "application/json", "text/csv"}


class Limits(BaseModel):
    max_file_bytes: int = 512 * 1024 * 1024
    max_files: int = 10_000
    max_total_bytes: int = 8 * 1024 * 1024 * 1024
    max_resources: int = 5_000_000


class ManifestFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    sha256: str

    @field_validator("path")
    @classmethod
    def _relative_safe(cls, v: str) -> str:
        p = PurePosixPath(v)
        if (
            not v
            or v.startswith("/")
            or "\\" in v
            or ":" in v
            or any(part in ("..", ".", "") for part in v.split("/"))
            or p.name == MANIFEST_NAME
        ):
            raise ValueError(f"unsafe or reserved path: {v!r}")
        return v

    @field_validator("sha256")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not SHA_RE.match(v):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return v

    @field_validator("mime_type")
    @classmethod
    def _mime(cls, v: str) -> str:
        if v not in ALLOWED_MIME:
            raise ValueError(f"unsupported mime type {v}")
        return v


class Generator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str
    parameters: dict[str, Any]


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest_version: Literal[1]
    source_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    source_revision: int = Field(gt=0)
    source_format: Literal["fhir-r4-bundle", "horizon-csv-v1", "horizon-json-v1"]
    schema_version: str
    synthetic: bool
    reference_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    generator: Generator
    files: list[ManifestFile] = Field(min_length=1)

    @field_validator("synthetic")
    @classmethod
    def _synthetic(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("synthetic must be true: HealthLake only accepts synthetic data")
        return v

    @model_validator(mode="after")
    def _sorted_unique(self) -> Manifest:
        paths = [f.path for f in self.files]
        if paths != sorted(paths):
            raise ValueError("files must be sorted by path")
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate file path")
        return self


def parse_manifest(raw: bytes, limits: Limits | None = None) -> tuple[Manifest, dict[str, Any], str]:
    """Return (model, logical manifest dict, batch_id). Raises ContractError."""
    limits = limits or Limits()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"manifest is not valid JSON: {exc}", code="manifest_invalid") from None
    try:
        model = Manifest.model_validate(data)
    except ValidationError as exc:
        msgs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
        raise ContractError(f"manifest invalid: {msgs}", code="manifest_invalid") from None
    if len(model.files) > limits.max_files:
        raise ContractError("too many files", code="limit_exceeded")
    for f in model.files:
        if f.size_bytes > limits.max_file_bytes:
            raise ContractError(f"file too large: {f.path}", code="limit_exceeded")
    if sum(f.size_bytes for f in model.files) > limits.max_total_bytes:
        raise ContractError("batch too large", code="limit_exceeded")
    logical = model.model_dump(mode="json")
    return model, logical, compute_batch_id(logical)


def scan_batch_dir(batch_dir: Path) -> list[str]:
    """List relative file paths (POSIX) under batch_dir, refusing symlinks and special files."""
    found: list[str] = []
    for root, dirs, files in os.walk(batch_dir, followlinks=False):
        for name in dirs + files:
            full = Path(root) / name
            st = full.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise ContractError(f"symbolic link not allowed: {full.relative_to(batch_dir)}", code="symlink")
            if name in files and not stat.S_ISREG(st.st_mode):
                raise ContractError(f"special file not allowed: {name}", code="special_file")
        for name in files:
            rel = (Path(root) / name).relative_to(batch_dir).as_posix()
            if rel != MANIFEST_NAME:
                found.append(rel)
    return sorted(found)
