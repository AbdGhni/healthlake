"""Runs the pinned HL7 validator (slow, needs Java and HEALTHLAKE_HL7_VALIDATOR_JAR)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from healthlake.pipelines.workspace import Workspace
from healthlake.validation.hl7 import run_audit
from tests.fixtures import factory as f

pytestmark = [pytest.mark.java, pytest.mark.slow]


@pytest.fixture
def jar() -> str:
    j = os.environ.get("HEALTHLAKE_HL7_VALIDATOR_JAR")
    if not j or not Path(j).is_file():
        pytest.skip("HEALTHLAKE_HL7_VALIDATOR_JAR not available")
    return j


def test_adapted_resources_pass_and_invalid_one_is_caught(jar: str, tmp_path: Path) -> None:
    from healthlake.adapters.base import AdaptedResource
    from healthlake.adapters.horizon import adapt_csv_batch
    from healthlake.generation.derive import to_csv_files

    ws = Workspace(tmp_path, "p" * 64)
    files = [(name, "x", data) for name, data in to_csv_files(f.business_rows(n_patients=1, obs_per_patient=1)).items()]
    adapted = [a for a in adapt_csv_batch(files) if isinstance(a, AdaptedResource)]
    bad = {"resourceType": "Patient", "id": "bad-patient", "gender": "banana"}
    records = [a.to_record(n) for n, a in enumerate(adapted, start=1)]
    records.append(
        {
            "n": len(records) + 1,
            "file": "x",
            "loc": "fixture#bad",
            "type": "Patient",
            "id": "bad-patient",
            "full_url": None,
            "resource": bad,
            "issues": [],
        }
    )
    ws.path("adapted.ndjson").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    summary = run_audit({"source_format": "horizon-csv-v1", "files": []}, ws, lambda sha: Path("/nonexistent"))
    assert summary["status"] == "completed"
    flagged = {i["locator"] for i in ws.read_json("hl7_issues.json")}
    assert flagged == {"fixture#bad"}, ws.read_json("hl7_issues.json")
