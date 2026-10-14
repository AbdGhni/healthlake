"""Conformance audit with the official HL7 FHIR validator (validator_cli 7.0.1), on a deterministic sample.

Why a sample: the validator needs ~20 s to start and ~30 s per 2 MB Synthea patient bundle on the
reference machine, i.e. ~50 min for 100 patients. Full validation would break the pipeline time budget.
Every resource is still checked by healthlake.validation.structural (the blocking gate); this audit adds
StructureDefinition/terminology conformance evidence and is reported, not blocking.
Runs offline: `-tx n/a` and packages pre-loaded in ~/.fhir/packages.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from healthlake.generation.synthea import load_json, verify_jar
from healthlake.pipelines.workspace import Workspace

ENTRY_RE = re.compile(r"^Bundle\.entry\[(\d+)\]")


def validator_jar() -> Path | None:
    p = os.environ.get("HEALTHLAKE_HL7_VALIDATOR_JAR")
    return Path(p) if p and Path(p).is_file() else None


def _sample_files(
    manifest: dict[str, Any], ws: Workspace, store_path: Any, policy: dict[str, Any]
) -> list[tuple[Path, str]]:
    """Return [(file to validate, logical name)]."""
    out: list[tuple[Path, str]] = []
    if manifest["source_format"] == "fhir-r4-bundle":
        files = [f for f in manifest["files"]]
        ref = [f for f in files if not f["path"].startswith("patients/")]
        pats = sorted((f for f in files if f["path"].startswith("patients/")), key=lambda f: f["path"])
        for f in ref + pats[: policy["sample"]["fhir_bundle_patient_files"]]:
            out.append((store_path(f["sha256"]), f["path"]))
        return out
    entries = []
    for rec in ws.ndjson("adapted.ndjson"):
        if rec["resource"] and rec["id"]:
            entries.append(
                {
                    "fullUrl": f"https://horizon.example/fhir/{rec['type']}/{rec['id']}",
                    "resource": rec["resource"],
                    "_loc": rec["loc"],
                }
            )
        if len(entries) >= policy["sample"]["horizon_resources"]:
            break
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [{k: v for k, v in e.items() if k != "_loc"} for e in entries],
    }
    p = ws.path("hl7_sample_bundle.json")
    p.write_text(json.dumps(bundle))
    ws.write_json("hl7_sample_locators.json", [e["_loc"] for e in entries])
    out.append((p, "adapted-sample"))
    return out


def run_audit(manifest: dict[str, Any], ws: Workspace, store_path: Any) -> dict[str, Any]:
    jar = validator_jar()
    if jar is None:
        summary: dict[str, Any] = {"status": "skipped", "reason": "HEALTHLAKE_HL7_VALIDATOR_JAR not set"}
        ws.write_json("hl7_issues.json", [])
        ws.mark_done("hl7", summary)
        return summary
    lock = load_json("artifact-lock.json")["artifacts"]["hl7_validator_cli"]
    verify_jar(jar, lock["sha256"])
    policy = load_json("hl7-validation-policy.json")
    targets = _sample_files(manifest, ws, store_path, policy)
    out_file = ws.path("hl7_result.json")
    java = shutil.which("java") or "java"
    cmd = [
        java,
        "-Xmx2g",
        "-jar",
        str(jar),
        *[str(t[0]) for t in targets],
        "-version",
        "4.0.1",
        "-tx",
        "n/a",
        "-output",
        str(out_file),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False)
    if not out_file.exists():
        raise RuntimeError(f"validator produced no output (exit {res.returncode}): {res.stderr[-300:]}")
    result = json.loads(out_file.read_text())
    sample_locs: list[str] = (
        ws.read_json("hl7_sample_locators.json") if ws.path("hl7_sample_locators.json").exists() else []
    )
    names = {str(t[0]): t[1] for t in targets}
    issues: list[dict[str, Any]] = []
    counts = {"fatal": 0, "error": 0, "warning": 0, "information": 0}
    entries = result.get("entry", []) if result.get("resourceType") == "Bundle" else [{"resource": result}]
    for e in entries:
        oo = e["resource"]
        fname = next((x.get("valueString") for x in oo.get("extension", []) if "file" in x.get("url", "")), "")
        logical = names.get(fname, Path(fname).name)
        for i in oo.get("issue", []):
            msg = i.get("details", {}).get("text") or i.get("diagnostics") or ""
            sev, cause = i.get("severity", "information"), "hl7_" + i.get("code", "issue")
            for rule in policy["reclassify"]:
                if rule["match"] in msg:
                    sev, cause = rule["severity"], rule["cause_code"]
                    break
            counts[sev] = counts.get(sev, 0) + 1
            if sev not in ("fatal", "error"):
                continue
            expr = (i.get("expression") or i.get("location") or [""])[0]
            m = ENTRY_RE.match(expr)
            if logical == "adapted-sample" and m and int(m.group(1)) < len(sample_locs):
                loc = sample_locs[int(m.group(1))]
            else:
                loc = f"{logical}#/entry/{m.group(1)}/resource" if m else logical
            issues.append(
                {
                    "check_id": "fhir.hl7_validator",
                    "severity": "warning",
                    "cause_code": cause,
                    "message": f"[hl7 {sev}] {msg[:400]}",
                    "locator": loc,
                    "file_sha256": None,
                }
            )
    summary = {
        "status": "completed",
        "validator": f"validator_cli {lock['version']}",
        "files": len(targets),
        "issue_counts": counts,
        "unexplained_errors": len(issues),
        "policy": policy["version"],
    }
    ws.write_json("hl7_issues.json", issues[:5000])
    ws.mark_done("hl7", summary)
    return summary
