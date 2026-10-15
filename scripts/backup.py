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
    paused: list[str] = []
    running_attempts = (
        "SELECT count(*) FROM ctl.attempt WHERE status='running' AND started_at > now() - interval '6 hours'"
    )
    active_runs = "SELECT count(*) FROM dag_run WHERE dag_id='healthlake_ingestion' AND state IN ('queued','running')"

    def busy() -> bool:
        if r.psql(a.db, running_attempts) != "0":
            return True
        return r.name == "docker" and r.psql("airflow", active_runs) != "0"

    try:
        # Stop new work first (discovery), let in-flight ingestion runs finish, then pause ingestion. Pausing the
        # ingestion DAG while one of its runs is in flight would freeze that run and its attempt (found by CI).
        if r.name == "docker":
            airflow("dags", "pause", "healthlake_discovery")
            paused.append("healthlake_discovery")
            print("[backup] discovery paused; waiting for in-flight ingestion runs and attempts to finish")
        deadline = time.time() + a.wait_seconds
        while True:
            while busy():
                if time.time() > deadline:
                    raise SystemExit("[backup] attempts still running; retry later (nothing was written)")
                time.sleep(10)
            if r.name != "docker":
                break
            airflow("dags", "pause", "healthlake_ingestion")
            paused.append("healthlake_ingestion")
            if not busy():
                print("[backup] ingestion paused; no run or attempt in flight")
                break
            airflow("dags", "unpause", "healthlake_ingestion")  # a run slipped in: let it finish and retry
            paused.remove("healthlake_ingestion")
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
        for d in paused:
            airflow("dags", "unpause", d)
        if paused:
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
