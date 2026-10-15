"""Measure the real pipeline (CLI + PostgreSQL + dbt + HL7 audit) for a generated profile.

For each source batch: wall time and peak RSS of the `healthlake ingest` process tree (largest single process,
from getrusage of children), per-step durations from ctl.event (clock_timestamp), counters. Then the release:
build-snapshot, dbt-build, dbt-docs, quality-gate, publish. Also database and directory sizes.

Usage (local development runner):
  python scripts/perf_pipeline.py --label demo-cold --out docs/performance/demo-cold.json
Environment: HEALTHLAKE_* variables of the target database and directories, HEALTHLAKE_LOCAL_CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

CLI = os.environ.get("HEALTHLAKE_LOCAL_CLI", "healthlake")


def timed(*args: str) -> tuple[dict[str, Any], float, float]:
    """Run the CLI under scripts/measure.py (fresh process: its child rusage is this command only)."""
    measure = Path(__file__).resolve().parent / "measure.py"
    res = subprocess.run([sys.executable, str(measure), CLI, *args], capture_output=True, text=True, check=False)
    out = json.loads(res.stdout.strip().splitlines()[-1])
    m = json.loads(res.stderr.strip().splitlines()[-1])["measure"]
    if res.returncode != 0:
        raise SystemExit(f"{args[0]} failed: {out}")
    return out, float(m["wall_s"]), float(m["peak_rss_mb"])


def psql(sql: str) -> str:
    dsn = (
        f"host={os.environ['HEALTHLAKE_DB_HOST']} port={os.environ['HEALTHLAKE_DB_PORT']} "
        f"user=postgres dbname={os.environ['HEALTHLAKE_DB_NAME']}"
    )
    return subprocess.run(["psql", dsn, "-Atc", sql], capture_output=True, text=True, check=True).stdout.strip()


def du(path: str) -> int:
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file()) if Path(path).exists() else 0


def step_durations(pid: str) -> dict[str, float]:
    rows = psql(
        "SELECT event, round(extract(epoch from occurred_at - lag(occurred_at) over (order by event_id))::numeric, 2)"
        f" FROM ctl.event WHERE processing_id='{pid}' ORDER BY event_id"
    ).splitlines()
    names = {
        "batch_archived": "archive",
        "adapted": "adapt",
        "processing_classified": "validate+resolve+classify",
        "normalized": "normalize",
        "silver_loaded": "load",
        "attempt_finished": "finish",
    }
    out: dict[str, float] = {}
    for line in rows:
        ev, _, secs = line.partition("|")
        if ev in names and secs:
            out[names[ev]] = float(secs)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gc-work", action="store_true", help="delete work files after each load (disk budget)")
    a = ap.parse_args()
    report: dict[str, Any] = {
        "label": a.label,
        "machine": {
            "cpu": platform.processor() or platform.machine(),
            "cpus": os.cpu_count(),
            "python": platform.python_version(),
            "kernel": platform.release(),
        },
        "batches": [],
        "release": {},
    }
    t_all = time.perf_counter()
    disc, _, _ = timed("discover")
    for bid in disc["pending_batch_ids"]:
        res, wall, rss = timed("ingest", "--batch-id", bid)
        pid = res["processing_id"]
        src = psql(f"SELECT b.source_id FROM ctl.batch b WHERE batch_id='{bid}'")
        c = res["counters"]
        work_bytes = du(os.path.join(os.environ["HEALTHLAKE_WORK_DIR"], pid))
        report["batches"].append(
            {
                "source_id": src,
                "status": res["status"],
                "wall_s": wall,
                "peak_rss_mb": rss,
                "received": c["received"],
                "accepted": c["accepted"],
                "rejected": c["rejected"],
                "out_of_scope": c["out_of_scope"],
                "steps_s": step_durations(pid),
                "work_dir_mb": round(work_bytes / 2**20),
            }
        )
        print(json.dumps(report["batches"][-1]), flush=True)
        if a.gc_work:
            timed("gc-work", "--older-than-hours", "0")
    rel: dict[str, Any] = {}
    out, rel["build_snapshot_s"], _ = timed("build-snapshot")
    rid = out["release_id"]
    rel["snapshot_members"] = out.get("snapshot", {}).get("members")
    _, rel["dbt_build_s"], rel["dbt_build_peak_rss_mb"] = timed("dbt-build", "--release-id", rid)
    _, rel["dbt_docs_s"], _ = timed("dbt-docs", "--release-id", rid)
    g, rel["quality_gate_s"], _ = timed("quality-gate", "--release-id", rid)
    _, rel["publish_s"], _ = timed("publish", "--release-id", rid)
    rel["gate_status"] = g["status"]
    schema = psql(f"SELECT schema_name FROM ctl.release WHERE release_id='{rid}'")
    rel["gold_rows"] = json.loads(
        psql(
            f"SELECT json_build_object('patients',(SELECT count(*) FROM {schema}.dim_patient),"
            f"'encounters',(SELECT count(*) FROM {schema}.fct_encounter),"
            f"'observations',(SELECT count(*) FROM {schema}.fct_observation),"
            f"'components',(SELECT count(*) FROM {schema}.fct_observation_component),"
            f"'conditions',(SELECT count(*) FROM {schema}.fct_condition),"
            f"'medication_requests',(SELECT count(*) FROM {schema}.fct_medication_request))"
        )
    )
    report["release"] = rel
    report["pipeline_total_s"] = round(time.perf_counter() - t_all, 1)
    report["database_size_mb"] = round(
        int(psql(f"SELECT pg_database_size('{os.environ['HEALTHLAKE_DB_NAME']}')")) / 2**20
    )
    report["dirs_mb"] = {
        k: round(du(os.environ[f"HEALTHLAKE_{k.upper()}_DIR"]) / 2**20)
        for k in ("landing", "lake", "work", "artifacts")
    }
    Path(a.out).write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("pipeline_total_s", "database_size_mb", "dirs_mb")}))
    print(json.dumps(rel))


if __name__ == "__main__":
    main()
