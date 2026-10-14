"""Content-addressed raw store (Bronze).

Application-level immutability: exclusive creation, no overwrite, hash verified on read.
This is not WORM storage: an administrator with filesystem access can still alter files;
`verify` and `reconcile` detect such changes.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO, Protocol

from healthlake.errors import HealthLakeError

CHUNK = 1024 * 1024


class IntegrityError(HealthLakeError):
    code = "bronze_integrity"


class RawStore(Protocol):
    def put_if_absent(self, sha256: str, src: BinaryIO) -> bool: ...
    def get(self, sha256: str) -> bytes: ...
    def exists(self, sha256: str) -> bool: ...
    def verify(self, sha256: str) -> bool: ...
    def list_referenced_objects(self, registry: Iterable[str]) -> dict[str, list[str]]: ...


class LocalRawStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def key(self, sha256: str) -> str:
        return f"sha256/{sha256[:2]}/{sha256[2:4]}/{sha256}"

    def path(self, sha256: str) -> Path:
        return self.root / self.key(sha256)

    def exists(self, sha256: str) -> bool:
        return self.path(sha256).is_file()

    def put_if_absent(self, sha256: str, src: BinaryIO) -> bool:
        """Store the stream under its hash. Returns True if created, False if it already existed.

        The stream is hashed while copied; a mismatch is refused. The final name is created with
        os.link, which fails if the target exists, so a stored object is never overwritten.
        """
        target = self.path(sha256)
        if target.exists():
            if not self.verify(sha256):
                raise IntegrityError(f"existing object {sha256} does not match its hash")
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".incoming-")
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := src.read(CHUNK):
                    h.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if h.hexdigest() != sha256:
                raise IntegrityError(f"content hash {h.hexdigest()} does not match expected {sha256}")
            os.chmod(tmp, 0o444)
            try:
                os.link(tmp, target)
                created = True
            except FileExistsError:
                created = False  # a concurrent writer won; verify below
        finally:
            os.unlink(tmp)
        if not created and not self.verify(sha256):
            raise IntegrityError(f"concurrent object {sha256} does not match its hash")
        return created

    def get(self, sha256: str) -> bytes:
        data = self.path(sha256).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise IntegrityError(f"object {sha256} failed verification on read")
        return data

    def verify(self, sha256: str) -> bool:
        p = self.path(sha256)
        if not p.is_file():
            return False
        h = hashlib.sha256()
        with p.open("rb") as f:
            while chunk := f.read(CHUNK):
                h.update(chunk)
        return h.hexdigest() == sha256

    def list_referenced_objects(self, registry: Iterable[str]) -> dict[str, list[str]]:
        """Reconcile registry hashes with stored objects: missing, corrupted, unregistered."""
        registered = set(registry)
        stored: set[str] = set()
        base = self.root / "sha256"
        if base.exists():
            for p in base.glob("*/*/*"):
                if p.is_file() and not p.name.startswith("."):
                    stored.add(p.name)
        missing = sorted(registered - stored)
        corrupted = sorted(s for s in registered & stored if not self.verify(s))
        unregistered = sorted(stored - registered)
        return {"missing": missing, "corrupted": corrupted, "unregistered": unregistered}
