"""Call the HealthLake CLI in its own virtualenv and map exit codes to Airflow retry semantics.

0 -> success (returns the compact JSON result; only ids and counters are pushed to XCom)
2 contract, 3 quality, 5 conflict -> AirflowFailException (no retry: the data must change)
4 transient, 1 unexpected -> RuntimeError (Airflow retries with exponential backoff)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

NO_RETRY = {2: "contract_invalid", 3: "quality_blocked", 5: "conflict"}
XCOM_KEYS = {
    "batch_id",
    "processing_id",
    "attempt_id",
    "release_id",
    "schema",
    "status",
    "received",
    "accepted",
    "deduplicated",
    "rejected",
    "out_of_scope",
    "reject_rate_new",
    "pending_batch_ids",
    "idempotent",
    "attempt_status",
}


def cli_path() -> str:
    return os.environ.get("HEALTHLAKE_CLI", "/opt/healthlake-venv/bin/healthlake")


def run_cli(*args: str, timeout: int = 1800) -> dict[str, Any]:
    from airflow.sdk.exceptions import AirflowFailException

    proc = subprocess.run([cli_path(), *args], capture_output=True, text=True, timeout=timeout, check=False)
    for line in proc.stderr.splitlines():  # structured JSON logs of the CLI, kept in the task log
        print(line, file=sys.stderr)
    try:
        result: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        result = {"raw": proc.stdout[-500:]}
    print(json.dumps({"healthlake_cli": args[0], "exit_code": proc.returncode, "result": result}))
    if proc.returncode == 0:
        return {k: v for k, v in result.items() if k in XCOM_KEYS}
    message = (
        f"healthlake {args[0]} failed with exit code {proc.returncode}: "
        f"{result.get('error_code')} {str(result.get('message', ''))[:300]}"
    )
    if proc.returncode in NO_RETRY:
        raise AirflowFailException(message)
    raise RuntimeError(message)
