"""Render docs/quality-catalog.md from config/quality-catalog.json (the catalog is the source of truth)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render() -> str:
    cat = json.loads((ROOT / "config" / "quality-catalog.json").read_text())
    plaus = json.loads((ROOT / "config" / "plausibility.json").read_text())
    lines = [
        f"# Quality catalogue ({cat['version']})",
        "",
        "Generated from `config/quality-catalog.json` by `scripts/gen_quality_catalog.py`. Do not edit by hand.",
        "",
        f"> {cat['note']}",
        "",
        "| Check | Category | Scope | Severity | Blocking | Threshold | Description | Implementation |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in cat["checks"]:
        thr = "" if c.get("threshold") is None else str(c["threshold"])
        lines.append(
            f"| `{c['id']}` | {c['category']} | {c['scope']} | {c['severity']} | "
            f"{'yes' if c['blocking'] else 'no'} | {thr} | {c['description']} | {c['implementation']} |"
        )
    lines += [
        "",
        "## Reconciliation",
        "",
        "Per processing: `received = accepted + deduplicated + rejected + out_of_scope`. Categories are disjoint and",
        "assigned in priority order rejected > deduplicated > out_of_scope > accepted (see docs/data-contract.md).",
        "",
        "## Quarantine",
        "",
        "Every error/fatal/warning is a row of `quality.issue` with processing_id, attempt_id, file hash, locator",
        "(JSON pointer or `file.csv#line=N`), source identity, check, severity, cause code, message,",
        "`caused_by_issue_id` (dependency cause), resolution status and the processing that resolved it.",
        "A correction is a new source revision; Bronze files are never modified.",
        "",
        "## Terminology (what is and is not checked)",
        "",
        "- Checked on every resource: R4 required value sets used by HealthLake"
        " (gender, statuses, intent, clinical status).",
        "- Measured per release: share of codings whose system URI is one of the known systems below.",
        "- Sample audit: the HL7 validator runs offline (`-tx n/a`),"
        " so it cannot validate SNOMED CT, LOINC or RxNorm codes.",
        "- Not checked: existence of a code in its code system, display text correctness, concept status.",
        "",
        "Known systems: " + ", ".join(f"`{s}`" for s in cat["known_code_systems"]),
        "",
        f"## Plausibility ranges ({plaus['version']})",
        "",
        f"> {plaus['note']}",
        "",
        "| LOINC | Label | Unit | Min | Max |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {r['code']} | {r['label']} | {r['unit']} | {r['min']} | {r['max']} |" for r in plaus["ranges"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    target = ROOT / "docs" / "quality-catalog.md"
    content = render()
    if "--check" in sys.argv:
        sys.exit(0 if target.exists() and target.read_text() == content else 1)
    target.write_text(content)
