from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECK_RE = re.compile(
    r'"((?:format|fhir|reference|identity|consistency|temporal|quarantine|reconciliation|release|'
    r'dbt|value|batch|bronze)\.[a-z_0-9]+)"'
)


def catalog_ids() -> set[str]:
    cat = json.loads((ROOT / "config" / "quality-catalog.json").read_text())
    ids = [c["id"] for c in cat["checks"]]
    assert len(ids) == len(set(ids)), "duplicate check id"
    return set(ids)


def test_every_check_emitted_by_code_is_catalogued() -> None:
    emitted = set()
    for p in (ROOT / "src").rglob("*.py"):
        emitted |= {m for m in CHECK_RE.findall(p.read_text()) if not m.endswith(".json")}
    from healthlake.normalization.project import TABLES

    missing = emitted - catalog_ids() - set(TABLES)  # schema.table literals are not check ids
    assert not missing, f"checks emitted but not in config/quality-catalog.json: {sorted(missing)}"


def test_generated_doc_is_up_to_date() -> None:
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_quality_catalog.py"), "--check"], check=False)
    assert res.returncode == 0, "run scripts/gen_quality_catalog.py"


def test_plausibility_flags_out_of_range_only() -> None:
    from healthlake.validation.plausibility import check_observation

    def obs(v: float, unit: str = "cm") -> dict[str, object]:
        return {
            "code": {"coding": [{"system": "http://loinc.org", "code": "8302-2"}]},
            "valueQuantity": {"value": v, "code": unit},
        }

    assert check_observation(obs(170), "x", None) == []
    assert [i.check_id for i in check_observation(obs(999), "x", None)] == ["value.extreme"]
    assert check_observation(obs(999, "[in_i]"), "x", None) == []  # other unit: no comparison, no conversion


def test_redaction() -> None:
    from healthlake.observability import redact

    s = redact("connection failed: host=x user=u password=s3cr3t dbname=d; url postgresql://u:p4ss@h/db")
    assert "s3cr3t" not in s and "p4ss" not in s and "password=***" in s


def test_openapi_export_is_up_to_date() -> None:
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "export_openapi.py"), "--check"], check=False)
    assert res.returncode == 0, "run scripts/export_openapi.py"
