"""Wait until the HealthLake stack is up: one-shot init jobs finished and every service healthy.

Standard library only. Exit 0 when ready, 1 with the failing component otherwise.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request

CHECKS = {
    "api": "http://127.0.0.1:8000/health/live",
    "airflow": "http://127.0.0.1:8080/api/v2/monitor/health",
    "dashboard": "http://127.0.0.1:8501/_stcore/health",
}
ONE_SHOT = ("db-init", "airflow-init")


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310 - fixed loopback URLs
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def compose_state() -> dict[str, dict[str, object]]:
    res = subprocess.run(
        ["docker", "compose", "ps", "--all", "--format", "json"], capture_output=True, text=True, check=False
    )
    out: dict[str, dict[str, object]] = {}
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        items = json.loads(line)
        for it in items if isinstance(items, list) else [items]:
            out[it.get("Service", "")] = it
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    deadline = time.time() + a.timeout
    last = ""
    while time.time() < deadline:
        state = compose_state()
        for job in ONE_SHOT:
            s = state.get(job, {})
            if s.get("State") == "exited" and s.get("ExitCode") not in (0, None):
                print(f"[wait_ready] {job} failed (exit {s.get('ExitCode')}). See: docker compose logs {job}")
                return 1
        pending = [n for n, url in CHECKS.items() if not http_ok(url)]
        pending += [j for j in ONE_SHOT if state.get(j, {}).get("State") != "exited"]
        if not pending:
            print(
                "[wait_ready] HealthLake is up: Airflow http://127.0.0.1:8080, API http://127.0.0.1:8000/docs, "
                "dashboard http://127.0.0.1:8501"
            )
            return 0
        msg = "waiting for: " + ", ".join(pending)
        if msg != last:
            print(f"[wait_ready] {msg}")
            last = msg
        time.sleep(5)
    print(
        f"[wait_ready] timeout after {a.timeout}s; still {last}. Check `docker compose ps` and "
        "`docker compose logs <service>`."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
