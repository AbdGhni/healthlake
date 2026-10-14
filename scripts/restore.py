"""Restore a HealthLake backup into clean volumes, then verify it.

Steps: check hashes of the backup files -> (docker) stop the stack and, only with --wipe-project-volumes, delete
this project's volumes -> start PostgreSQL -> restore roles (without passwords) and databases -> db-init sets the
role passwords from .secrets -> restore Bronze, artifacts, landing ->
verify Bronze objects against their hashes -> compare reconciliation counts with the manifest -> start the stack ->
API smoke test: active release and summary.

  python scripts/restore.py --from backups/20261014T200000Z --wipe-project-volumes
  python scripts/restore.py --from <dir> --runner local --db healthlake_restored   (development)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ops import COUNT_SQL, DATA_PARTS, copy_secrets_hint, runner, sha256_file

VOLUMES = ["pg_data", "landing", "lake", "work", "artifacts", "airflow_logs"]


def sh(*cmd: str) -> None:
    res = subprocess.run(list(cmd), capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise SystemExit(f"[restore] {' '.join(cmd)} failed: {res.stderr[-500:]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--runner", choices=["docker", "local"], default="docker")
    ap.add_argument("--db", default="healthlake")
    ap.add_argument(
        "--wipe-project-volumes",
        action="store_true",
        help="docker: delete this project's volumes before restoring (irreversible)",
    )
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--api-key", default=None, help="analyst key; default: .secrets/api_keys_plain.json")
    a = ap.parse_args()
    src = Path(a.src)
    manifest = json.loads((src / "manifest.json").read_text())
    for name, meta in manifest["files"].items():
        if sha256_file(src / name) != meta["sha256"]:
            raise SystemExit(f"[restore] {name} does not match the manifest hash; backup corrupted")
    print("[restore] backup files verified against manifest hashes")
    r = runner(a.runner)
    if r.name == "docker":
        if not a.wipe_project_volumes:
            raise SystemExit(
                "[restore] restore needs clean volumes: re-run with --wipe-project-volumes (deletes "
                "only volumes of the 'healthlake' compose project)"
            )
        sh("docker", "compose", "down")
        for v in VOLUMES:
            subprocess.run(["docker", "volume", "rm", f"healthlake_{v}"], capture_output=True, check=False)
        sh("docker", "compose", "up", "-d", "postgres")
        for _ in range(60):
            if (
                subprocess.run(
                    ["docker", "compose", "exec", "-T", "postgres", "pg_isready", "-U", "healthlake_owner"],
                    capture_output=True,
                    check=False,
                ).returncode
                == 0
            ):
                break
            time.sleep(2)
        r.restore_globals(src / "globals.sql")
        r.restore(a.db, src / "healthlake.dump")
        if "airflow.dump" in manifest["files"]:
            r.restore("airflow", src / "airflow.dump")
    else:
        if r.psql("postgres", f"SELECT count(*) FROM pg_database WHERE datname='{a.db}'") != "0":
            raise SystemExit(f"[restore] database {a.db} already exists; restore needs a clean target")
        r.psql("postgres", f'CREATE DATABASE "{a.db}" OWNER healthlake_owner')
        r.restore_globals(src / "globals.sql")
        r.restore(a.db, src / "healthlake.dump")
    r.reset_role_passwords()
    print("[restore] databases restored; role passwords set again from .secrets (backups hold no password)")
    for part in DATA_PARTS:
        r.unarchive(part, src / f"{part}.tgz")
    print("[restore] Bronze, artifacts and landing restored")
    vb = r.cli("verify-bronze")
    if vb["_exit"] != 0 or vb.get("missing") or vb.get("corrupted"):
        raise SystemExit(f"[restore] Bronze verification failed: {vb}")
    print(f"[restore] Bronze verified: {vb.get('registered')} objects, 0 missing, 0 corrupted")
    counts = json.loads(r.psql(a.db, COUNT_SQL))
    if counts != manifest["counts"]:
        raise SystemExit(f"[restore] reconciliation failed: {counts} != {manifest['counts']}")
    print(f"[restore] reconciliation counts match the manifest: {counts}")
    schema = r.psql(a.db, "SELECT r.schema_name FROM ctl.active_release a JOIN ctl.release r USING (release_id)")
    if counts["active_release"] and r.psql(a.db, f"SELECT count(*) FROM pg_namespace WHERE nspname='{schema}'") != "1":
        raise SystemExit("[restore] the active release schema is missing")
    if r.name == "docker":
        sh("docker", "compose", "up", "-d")
        sh(sys.executable, str(Path(__file__).resolve().parent / "wait_ready.py"))
    key = (
        a.api_key
        or json.loads((Path(__file__).resolve().parents[1] / ".secrets" / "api_keys_plain.json").read_text())["analyst"]
    )
    for _ in range(30):
        try:
            if not a.api.startswith(("http://", "https://")):
                raise SystemExit("[restore] --api must be an http(s) URL")
            req = urllib.request.Request(f"{a.api}/v1/summary", headers={"X-API-Key": key})  # noqa: S310
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - loopback URL from arguments
                summary = json.loads(resp.read())
            break
        except OSError:
            time.sleep(3)
    else:
        raise SystemExit("[restore] API smoke test failed")
    if summary["release_id"] != counts["active_release"]:
        raise SystemExit("[restore] the API serves another release than the restored active one")
    print(f"[restore] API smoke test ok: release {summary['release_id'][:12]}, {summary['patients']} patients")
    print(f"[restore] done. {copy_secrets_hint()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
