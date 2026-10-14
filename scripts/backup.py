"""Consistent backup of HealthLake: pause new processing, dump databases and roles, archive Bronze, artifacts and
landing, write a manifest of SHA-256 hashes and reconciliation counts, resume.

  python scripts/backup.py                 # Docker Compose stack, output in backups/<UTC timestamp>/
  python scripts/backup.py --runner local  # development setup (see scripts/_ops.py)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ops import COUNT_SQL, DATA_PARTS, ROOT, copy_secrets_hint, runner, sha256_file

DAGS = ("healthlake_discovery", "healthlake_ingestion")


def airflow(*args: str) -> None:
    subprocess.run(
        ["docker", "compose", "exec", "-T", "airflow-api-server", "airflow", *args], capture_output=True, check=False
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runner", choices=["docker", "local"], default="docker")
    ap.add_argument("--out", default=str(ROOT / "backups"))
    ap.add_argument("--db", default="healthlake")
    ap.add_argument("--wait-seconds", type=int, default=900)
    a = ap.parse_args()
    r = runner(a.runner)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(a.out) / stamp
    out.mkdir(parents=True)
    paused = False
    try:
        if r.name == "docker":
            for d in DAGS:
                airflow("dags", "pause", d)
            paused = True
            print("[backup] Airflow DAGs paused; waiting for running attempts to finish")
        deadline = time.time() + a.wait_seconds
        while (
            r.psql(
                a.db,
                "SELECT count(*) FROM ctl.attempt WHERE status='running' AND started_at > now() - interval '6 hours'",
            )
            != "0"
        ):
            if time.time() > deadline:
                raise SystemExit("[backup] attempts still running; retry later (nothing was written)")
            time.sleep(10)
        counts = json.loads(r.psql(a.db, COUNT_SQL))
        r.dump_globals(out / "globals.sql")
        r.dump(a.db, out / "healthlake.dump")
        if r.name == "docker":
            r.dump("airflow", out / "airflow.dump")
        for part in DATA_PARTS:
            r.archive(part, out / f"{part}.tgz")
        after = json.loads(r.psql(a.db, COUNT_SQL))
        if after != counts:
            raise SystemExit("[backup] data changed during the backup; retry (consistency check failed)")
    finally:
        if paused:
            for d in DAGS:
                airflow("dags", "unpause", d)
            print("[backup] Airflow DAGs resumed")
    files = {p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size} for p in sorted(out.iterdir())}
    manifest = {
        "created_at": stamp,
        "runner": r.name,
        "database": a.db,
        "counts": counts,
        "files": files,
        "notes": [copy_secrets_hint(), "work/ is not backed up (rebuildable)."],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"[backup] done: {out}")
    print(f"[backup] counts: {counts}")
    print(f"[backup] {copy_secrets_hint()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
