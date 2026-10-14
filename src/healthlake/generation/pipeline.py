"""`healthlake generate`: three Synthea populations -> three Horizon sources -> finalized batches."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from healthlake.config import paths
from healthlake.generation.batch_writer import write_batch
from healthlake.generation.derive import extract_rows, to_csv_files, to_json_files
from healthlake.generation.synthea import collect_fhir, load_json, run_synthea


def generate(profile: str, revision: int, jar: str, only: list[str] | None = None) -> dict[str, Any]:
    cfg = load_json("sources.json")
    prof = load_json("profiles.json")
    population = prof["profiles"][profile]["population"]
    out: list[dict[str, Any]] = []
    for src in cfg["sources"]:
        if only and src["source_id"] not in only:
            continue
        s = src["synthea"]
        with tempfile.TemporaryDirectory(dir=paths().work) as tmp:
            gen = run_synthea(Path(jar), Path(tmp) / "synthea", s["seed"], s["clinician_seed"], population, s["state"])
            fhir = collect_fhir(Path(tmp) / "synthea")
        gen["parameters"]["profile"] = profile
        if src["source_format"] == "fhir-r4-bundle":
            files = fhir
            mime = dict.fromkeys(files, "application/fhir+json")
        else:
            rows = extract_rows(fhir)
            files = to_csv_files(rows) if src["source_format"] == "horizon-csv-v1" else to_json_files(rows)
            mime = {}
            gen["parameters"]["derivation"] = f"healthlake.generation.derive:{src['source_format']}"
        patients = sum(1 for k in fhir if k.startswith("patients/"))
        final, bid = write_batch(
            paths().landing,
            src["source_id"],
            revision,
            src["source_format"],
            src["schema_version"],
            prof["reference_date"],
            gen,
            files,
            mime,
        )
        out.append(
            {
                "source_id": src["source_id"],
                "batch_id": bid,
                "path": str(final),
                "patients_exported": patients,
                "files": len(files),
            }
        )
    return {"profile": profile, "revision": revision, "batches": out}
