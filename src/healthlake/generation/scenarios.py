"""Scenario batches for demonstrations, derived from the original loaded horizon-nord batch (synthetic).

Every scenario revision starts from the same original content, so scenarios do not inherit each other's defects.

- quarantine: copies the batch as a new revision and adds 120 NEW observations (copies of existing quantity
  observations under new ids) of which exactly one has a non-numeric value: 1/120 = 0.83 % of the new resources,
  under the 1 % gate, so the batch is published with one quarantined resource. (Corrupting an existing
  observation would be an invalid update of a known identity, which blocks the batch by design.)
- extend: same as quarantine without any corrupted value (used by the recovery scenario);
- invalid: copies the batch as a new revision with a wrong patients.csv header (fatal, processing blocked).
The corruption is explicit and documented; nothing else changes.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from healthlake.config import paths
from healthlake.db import connect
from healthlake.errors import ContractError
from healthlake.generation.batch_writer import write_batch
from healthlake.pipelines.runner import store


def make_scenario_batch(kind: str) -> dict[str, Any]:
    with connect("ingest") as conn:
        row = conn.execute(
            "SELECT b.batch_id, b.source_revision, b.manifest FROM ctl.batch b JOIN ctl.processing p USING (batch_id)"
            " WHERE b.source_id='horizon-nord' AND p.status='loaded'"
            " AND b.manifest->'generator'->>'name' <> 'healthlake-scenario' ORDER BY b.source_revision LIMIT 1"
        ).fetchone()
        top = conn.execute("SELECT max(source_revision) FROM ctl.batch WHERE source_id='horizon-nord'").fetchone()
    if row is None or top is None:
        raise ContractError(
            "no archived horizon-nord batch to derive from; run the happy path first", code="nothing_to_derive"
        )
    _, _, manifest = row
    files = {f["path"]: store().get(f["sha256"]) for f in manifest["files"]}
    if kind in ("quarantine", "extend"):
        text = files["observations.csv"].decode("utf-8")
        rows = list(csv.reader(io.StringIO(text, newline="")))
        header = rows[0]
        oi, vi, ti = header.index("observation_id"), header.index("value"), header.index("value_type")
        revision_tag = f"r{int(top[0]) + 1}"
        sources = [r for r in rows[1:] if r[ti] == "quantity"][:120]
        if len(sources) < 120:
            raise ContractError("not enough observations to build the scenario", code="nothing_to_derive")
        added = []
        for i, src in enumerate(sources):
            new = list(src)
            new[oi] = f"{src[oi]}-{revision_tag}-{i}"
            added.append(new)
        if kind == "quarantine":
            added[0][vi] = "not-a-number"
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(rows + added)
        files["observations.csv"] = buf.getvalue().encode("utf-8")
        detail = (
            f"120 new observations added (copies under new ids), observation {added[0][oi]} has value 'not-a-number'"
        )
    elif kind == "invalid":
        files["patients.csv"] = files["patients.csv"].replace(b"patient_id,", b"patient_identifier,", 1)
        detail = "patients.csv header renamed (patient_id -> patient_identifier)"
    else:
        raise ContractError(f"unknown scenario kind {kind}", code="invalid_parameter")
    revision = int(top[0]) + 1
    generator = {
        "name": "healthlake-scenario",
        "version": "1",
        "parameters": {"kind": kind, "derived_from_revision": int(row[1]), "change": detail},
    }
    _final, bid = write_batch(
        paths().landing,
        "horizon-nord",
        revision,
        manifest["source_format"],
        manifest["schema_version"],
        manifest["reference_date"],
        generator,
        files,
    )
    return {"kind": kind, "batch_id": bid, "source_id": "horizon-nord", "revision": revision, "change": detail}
