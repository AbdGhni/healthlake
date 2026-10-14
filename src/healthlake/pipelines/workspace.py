"""Per-processing work directory. Each step writes its outputs atomically (tmp + rename) and a
done marker, so a re-run after a crash either finds a complete output or rebuilds it."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any


class Workspace:
    def __init__(self, root: Path, processing_id: str) -> None:
        self.dir = root / processing_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.dir / name

    def done(self, step: str) -> dict[str, Any] | None:
        p = self.path(f"{step}.done.json")
        if p.exists():
            data: dict[str, Any] = json.loads(p.read_text())
            return data
        return None

    def mark_done(self, step: str, summary: dict[str, Any]) -> None:
        self.write_json(f"{step}.done.json", summary)

    def write_json(self, name: str, obj: Any) -> None:
        tmp = self.path(f"{name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":")))
        os.replace(tmp, self.path(name))

    def read_json(self, name: str) -> Any:
        return json.loads(self.path(name).read_text())

    def ndjson_writer(self, name: str) -> NdjsonWriter:
        return NdjsonWriter(self.path(name))

    def ndjson(self, name: str) -> Iterator[dict[str, Any]]:
        with self.path(name).open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


class NdjsonWriter:
    def __init__(self, final: Path) -> None:
        self.final = final
        self.tmp = final.with_name(f"{final.name}.{uuid.uuid4().hex}.tmp")
        self.f = self.tmp.open("w", encoding="utf-8")
        self.count = 0

    def write(self, obj: Any) -> None:
        self.f.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=True))
        self.f.write("\n")
        self.count += 1

    def commit(self) -> None:
        self.f.flush()
        os.fsync(self.f.fileno())
        self.f.close()
        os.replace(self.tmp, self.final)

    def __enter__(self) -> NdjsonWriter:
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.f.close()
            self.tmp.unlink(missing_ok=True)
