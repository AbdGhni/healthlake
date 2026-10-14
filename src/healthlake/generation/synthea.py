"""Run pinned Synthea for one source population and collect its FHIR output."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from healthlake.errors import ContractError, HealthLakeError

REPO_ROOT = Path(__file__).resolve().parents[3]


def load_json(rel: str) -> dict[str, Any]:
    base = Path(os.environ.get("HEALTHLAKE_CONFIG_DIR", REPO_ROOT / "config"))
    data: dict[str, Any] = json.loads((base / rel).read_text(encoding="utf-8"))
    return data


def verify_jar(jar: Path, expected_sha256: str) -> None:
    h = hashlib.sha256()
    with jar.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    if h.hexdigest() != expected_sha256:
        raise ContractError(f"{jar.name} sha256 mismatch", code="artifact_hash_mismatch")


def run_synthea(
    jar: Path, out_dir: Path, seed: int, clinician_seed: int, population: int, state: str
) -> dict[str, Any]:
    lock = load_json("artifact-lock.json")["artifacts"]["synthea"]
    verify_jar(jar, lock["sha256"])
    prof = load_json("profiles.json")
    ref = prof["reference_date"].replace("-", "")
    end = prof["simulation_end_date"].replace("-", "")
    props = Path(os.environ.get("HEALTHLAKE_CONFIG_DIR", REPO_ROOT / "config")) / "synthea" / "healthlake.properties"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    java = shutil.which("java")
    if java is None:
        raise HealthLakeError("java not found", code="java_missing")
    args = [
        java,
        "-Duser.timezone=UTC",
        "-Dfile.encoding=UTF-8",
        "-Dsun.jnu.encoding=UTF-8",
        "-jar",
        str(jar),
        "-s",
        str(seed),
        "-cs",
        str(clinician_seed),
        "-r",
        ref,
        "-e",
        end,
        "-p",
        str(population),
        "-c",
        str(props),
        f"--exporter.baseDirectory={out_dir}/",
        f"--exporter.years_of_history={prof['years_of_history']}",
        f"--generate.thread_pool_size={prof['thread_pool_size']}",
        state,
    ]
    env = {**os.environ, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"}
    res = subprocess.run(args, capture_output=True, text=True, env=env, timeout=7200, check=False)
    if res.returncode != 0:
        raise HealthLakeError(f"synthea failed: {res.stderr[-500:]}", code="synthea_failed")
    if "Exception" in res.stdout:
        raise HealthLakeError("synthea reported an exception", code="synthea_failed")
    return {
        "name": "synthea",
        "version": lock["version"],
        "parameters": {
            "seed": seed,
            "clinician_seed": clinician_seed,
            "population": population,
            "state": state,
            "reference_date": prof["reference_date"],
            "end_date": prof["simulation_end_date"],
            "years_of_history": prof["years_of_history"],
            "thread_pool_size": prof["thread_pool_size"],
            "timezone": "UTC",
            "jar_sha256": lock["sha256"],
        },
    }


def collect_fhir(out_dir: Path) -> dict[str, bytes]:
    """Return {relative name: bytes} for Synthea FHIR bundles, deterministic names."""
    fhir = out_dir / "fhir"
    files: dict[str, bytes] = {}
    for p in sorted(fhir.glob("*.json")):
        name = p.name
        if name.startswith("hospitalInformation"):
            name = "hospitalInformation.json"
        elif name.startswith("practitionerInformation"):
            name = "practitionerInformation.json"
        else:
            name = f"patients/{name}"
        files[name] = p.read_bytes()
    return files
