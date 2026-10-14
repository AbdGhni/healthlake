"""HealthLake demonstration scenarios on the real system.

  python scripts/demo.py --scenario happy-path            (Docker stack: Synthea -> Airflow -> API)
  python scripts/demo.py --scenario quarantine
  python scripts/demo.py --scenario idempotent-replay
  python scripts/demo.py --scenario blocked-publication
  python scripts/demo.py --scenario recovery
  python scripts/demo.py --scenario all

`--runner local` runs the same scenarios without Docker, calling the `healthlake` CLI directly instead of Airflow
(used to verify the scenarios in a development environment). Each scenario checks its expected outcome and exits
non-zero if the system did not behave as documented. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".secrets"


class ScenarioFailed(SystemExit):
    pass


def say(msg: str) -> None:
    print(f"[demo] {msg}", flush=True)


def expect(cond: bool, what: str) -> None:
    if not cond:
        raise ScenarioFailed(f"[demo] EXPECTATION FAILED: {what}")
    say(f"ok: {what}")


class Runner:
    def __init__(self, mode: str, api: str, airflow: str, keys_file: Path, profile: str) -> None:
        self.mode, self.api_url, self.airflow_url, self.profile = mode, api.rstrip("/"), airflow.rstrip("/"), profile
        self.keys = json.loads(keys_file.read_text())
        self._token: str | None = None

    # ------------------------------------------------------------------ CLI
    def cli(self, *args: str, env: dict[str, str] | None = None, check: bool = True) -> dict[str, Any]:
        if self.mode == "docker":
            extra = [x for k, v in (env or {}).items() for x in ("-e", f"{k}={v}")]
            cmd = ["docker", "compose", "run", "--rm", "--no-deps", *extra, "cli", *args]
            full_env = None
        else:
            cmd = [os.environ.get("HEALTHLAKE_LOCAL_CLI", "healthlake"), *args]
            full_env = {**os.environ, **(env or {})}
        res = subprocess.run(cmd, capture_output=True, text=True, env=full_env, check=False)
        line = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else "{}"
        try:
            out: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            out = {"ok": False, "raw": res.stdout[-500:]}
        out["_exit"] = res.returncode
        if check and res.returncode != 0:
            raise ScenarioFailed(f"[demo] healthlake {' '.join(args)} failed ({res.returncode}): {line[:400]}")
        return out

    def generate(self, revision: int) -> list[str]:
        if self.mode == "docker":
            res = subprocess.run(
                [
                    "docker",
                    "compose",
                    "run",
                    "--rm",
                    "--no-deps",
                    "synthea",
                    "--profile",
                    self.profile,
                    "--revision",
                    str(revision),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                raise ScenarioFailed(f"[demo] generation failed: {res.stdout[-400:]} {res.stderr[-400:]}")
            out = json.loads(res.stdout.strip().splitlines()[-1])
        else:
            out = self.cli(
                "generate",
                "--profile",
                self.profile,
                "--revision",
                str(revision),
                "--jar",
                os.environ["HEALTHLAKE_SYNTHEA_JAR"],
            )
        for b in out["batches"]:
            say(f"  {b['source_id']}: {b['patients_exported']} patients exported, batch {b['batch_id'][:12]}")
        return [b["batch_id"] for b in out["batches"]]

    # ------------------------------------------------------------------ orchestration
    def process(self, batch_ids: list[str], env: dict[str, str] | None = None) -> dict[str, str]:
        """Run batches through the real orchestrator; return {batch_id: final state}."""
        disc = self.cli("discover")
        pending = set(disc.get("pending_batch_ids", []))
        if self.mode == "local":
            states = {}
            for bid in batch_ids:
                if bid not in pending:
                    states[bid] = "already processed"
                    continue
                r = self.cli("ingest", "--batch-id", bid, env=env, check=False)
                states[bid] = r.get("status") or r.get("error_code", "failed")
            if any(s == "succeeded" for s in states.values()):
                self.release_cycle(env)
            return states
        self.airflow("POST", "/api/v2/dags/healthlake_discovery/dagRuns", {"logical_date": None})
        return {bid: self.wait_run(f"batch__{bid}") for bid in batch_ids if bid in pending}

    def release_cycle(self, env: dict[str, str] | None = None) -> str:
        rel = self.cli("build-snapshot", env=env)
        rid = rel["release_id"]
        self.cli("dbt-build", "--release-id", rid, env=env)
        self.cli("dbt-docs", "--release-id", rid, env=env)
        self.cli("quality-gate", "--release-id", rid, env=env)
        self.cli("publish", "--release-id", rid, env=env)
        return str(rid)

    def airflow(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        if self._token is None:
            pw = (SECRETS / "airflow_admin_password").read_text().strip()
            self._token = self._http("POST", f"{self.airflow_url}/auth/token", {"username": "admin", "password": pw})[
                "access_token"
            ]
        return self._http(method, f"{self.airflow_url}{path}", body, {"Authorization": f"Bearer {self._token}"})

    def wait_run(self, run_id: str, timeout: int = 1800) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                state = self.airflow("GET", f"/api/v2/dags/healthlake_ingestion/dagRuns/{run_id}")["state"]
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                state = "not yet triggered"
            if state in ("success", "failed"):
                say(f"  Airflow run {run_id[:24]}...: {state}")
                return "succeeded" if state == "success" else "failed"
            time.sleep(10)
        raise ScenarioFailed(f"[demo] timeout waiting for {run_id}")

    # ------------------------------------------------------------------ API
    def api(self, path: str, who: str = "analyst", allow_error: bool = False) -> dict[str, Any]:
        try:
            return self._http("GET", f"{self.api_url}{path}", None, {"X-API-Key": self.keys[who]})
        except urllib.error.HTTPError as e:
            if allow_error:
                return {"_status": e.code, **json.loads(e.read() or b"{}")}
            raise

    @staticmethod
    def _http(method: str, url: str, body: Any = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            raise ValueError("only http(s) URLs")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(  # noqa: S310 - scheme checked above
            url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})}
        )
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - loopback URLs from arguments
            out: dict[str, Any] = json.loads(r.read() or b"{}")
            return out


def active_release(r: Runner) -> str | None:
    res = r.api("/v1/releases/current", allow_error=True)
    return res.get("release_id") if "_status" not in res else None


def scenario_happy_path(r: Runner) -> None:
    say("happy-path: generate 3 synthetic sources with Synthea, ingest them, publish, read through the API")
    batches = r.generate(revision=1)
    states = r.process(batches)
    expect(all(s in ("succeeded", "already processed") for s in states.values()), f"all batches processed {states}")
    s = r.api("/v1/summary")
    say(
        f"  release {s['release_id'][:12]}: {s['patients']} patients, {s['encounters']} encounters, "
        f"{s['observations']} observations, {s['medication_requests']} prescriptions"
    )
    expect(s["patients"] > 0 and s["encounters"] > 0, "a published release with data is served by the API")


def scenario_quarantine(r: Runner) -> None:
    say("quarantine: a new horizon-nord revision with one corrupted observation value (<= 1 % of new resources)")
    b = r.cli("scenario-batch", "--kind", "quarantine")
    say(f"  {b['change']} (revision {b['revision']}, batch {b['batch_id'][:12]})")
    states = r.process([b["batch_id"]])
    expect(states.get(b["batch_id"]) == "succeeded", "the batch is published despite one quarantined resource")
    q = r.api("/v1/quality", who="operator")
    rows = [i for i in q["issues"] if i["check_id"] == "format.row"]
    expect(bool(rows), f"the quarantined row is reported by /v1/quality ({rows})")


def scenario_idempotent_replay(r: Runner) -> None:
    say("idempotent-replay: ingest an already loaded batch again")
    before = r.api("/v1/summary")
    runs = r.api("/v1/pipeline-runs?status=succeeded&limit=1", who="operator")["data"]
    expect(bool(runs), "there is a succeeded batch to replay")
    bid = runs[0]["batch_id"]
    if r.mode == "local":
        r.cli("ingest", "--batch-id", bid)
        r.release_cycle()
    else:
        run_id = f"replay__{bid[:16]}__{int(time.time())}"
        r.airflow(
            "POST",
            "/api/v2/dags/healthlake_ingestion/dagRuns",
            {"dag_run_id": run_id, "logical_date": None, "conf": {"batch_id": bid}},
        )
        expect(r.wait_run(run_id) == "succeeded", "the replay run succeeds")
    after = r.api("/v1/summary")
    expect(after["release_id"] == before["release_id"], "same inputs give the same release id")
    expect(after["observations"] == before["observations"], "no duplicated resource")


def scenario_blocked_publication(r: Runner) -> None:
    say(
        "blocked-publication: (1) an invalid batch is blocked at the processing gate; (2) a release whose dbt tests "
        "fail (explicit demo fault injection) is refused; the active release never changes"
    )
    active = active_release(r)
    b = r.cli("scenario-batch", "--kind", "invalid")
    say(f"  {b['change']} (revision {b['revision']})")
    states = r.process([b["batch_id"]])
    expect(states.get(b["batch_id"]) != "succeeded", f"the invalid batch is not published ({states})")
    expect(active_release(r) == active, "active release unchanged after the blocked batch")
    env = {"HEALTHLAKE_INJECT_GATE_FAILURE": "1"}
    rel = r.cli("build-snapshot", env=env)
    r.cli("dbt-build", "--release-id", rel["release_id"], env=env)
    gate = r.cli("quality-gate", "--release-id", rel["release_id"], env=env, check=False)
    expect(gate["_exit"] == 3 and gate.get("error_code") == "release_gate_failed", "the release gate fails")
    pub = r.cli("publish", "--release-id", rel["release_id"], check=False)
    expect(pub["_exit"] == 3, "publication of the failed release is refused")
    expect(active_release(r) == active, "active release unchanged after the refused publication")


def scenario_recovery(r: Runner) -> None:
    say("recovery: a crash during the Silver load, then a normal re-run")
    b = r.cli("scenario-batch", "--kind", "extend")
    r.cli("discover")
    crash = r.cli("ingest", "--batch-id", b["batch_id"], env={"HEALTHLAKE_CRASH_AT": "during_load"}, check=False)
    expect(crash["_exit"] != 0, "the injected crash interrupts the run")
    again = r.cli("ingest", "--batch-id", b["batch_id"])
    expect(again["status"] == "succeeded", "the re-run succeeds from where the work is safe to resume")
    rid = r.release_cycle()
    runs = r.api("/v1/pipeline-runs?limit=5", who="operator")["data"]
    statuses = [x["status"] for x in runs if x["batch_id"] == b["batch_id"]]
    expect("failed" in statuses and "succeeded" in statuses, f"both attempts are recorded ({statuses})")
    expect(active_release(r) == rid, "the recovered batch is published")


SCENARIOS = {
    "happy-path": scenario_happy_path,
    "quarantine": scenario_quarantine,
    "idempotent-replay": scenario_idempotent_replay,
    "blocked-publication": scenario_blocked_publication,
    "recovery": scenario_recovery,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=[*SCENARIOS, "all"], required=True)
    ap.add_argument("--runner", choices=["docker", "local"], default="docker")
    ap.add_argument("--profile", choices=["test", "demo", "extended"], default="demo")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--airflow", default="http://127.0.0.1:8080")
    ap.add_argument("--keys", default=str(SECRETS / "api_keys_plain.json"))
    a = ap.parse_args()
    print("HealthLake demo - synthetic data only; not a certified healthcare platform.")
    r = Runner(a.runner, a.api, a.airflow, Path(a.keys), a.profile)
    names = list(SCENARIOS) if a.scenario == "all" else [a.scenario]
    for name in names:
        t0 = time.time()
        SCENARIOS[name](r)
        say(f"{name}: passed in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
