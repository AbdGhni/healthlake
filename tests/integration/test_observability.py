"""Quality observations and operational signals on the real pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures import factory as f
from tests.integration.helpers import issues, one, run

pytestmark = pytest.mark.db


def test_extreme_value_is_flagged_not_rejected(lake: dict[str, Path]) -> None:
    entries = f.fhir_population(n_patients=1, obs_per_patient=2)
    obs = next(e for e in entries if e["resource"]["resourceType"] == "Observation")
    obs["resource"]["valueQuantity"]["value"] = 999.0  # body height 999 cm
    r = run(lake["landing"], f.write_fhir_batch(lake["landing"], entries))
    assert r["ok"] and r["counters"]["rejected"] == 0
    (row,) = issues("value_out_of_plausible_range")
    assert row[0] == "value.extreme" and row[1] == "warning"
    assert one("SELECT count(*) FROM silver.observation WHERE value_numeric = 999") == 1  # kept as received


def test_metrics_have_bounded_labels_and_no_ids(lake: dict[str, Path]) -> None:
    from healthlake.metrics import render_text

    b = f.write_csv_batch(lake["landing"], f.business_rows())
    r = run(lake["landing"], b)
    text = render_text("api")
    assert "healthlake_metrics_db_up 1.0" in text
    assert 'healthlake_resources{outcome="accepted",resource_type="Observation",source_id="horizon-nord"} 6.0' in text
    assert 'healthlake_attempts{status="succeeded"} 1.0' in text
    assert "healthlake_last_success_timestamp_seconds" in text
    assert b not in text and r["processing_id"] not in text and r["attempt_id"] not in text


def test_metrics_report_db_down_instead_of_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    from healthlake.metrics import render_text

    monkeypatch.setenv("HEALTHLAKE_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("HEALTHLAKE_DB_PORT", "1")
    assert "healthlake_metrics_db_up 0.0" in render_text("api")


def test_cli_never_prints_the_password(lake: dict[str, Path], tmp_path: Path) -> None:
    secret_file = tmp_path / "wrong"
    secret_file.write_text("Sup3r-Secret-Value")
    env = {
        **os.environ,
        "HEALTHLAKE_DB_INGEST_PASSWORD_FILE": str(secret_file),
        "HEALTHLAKE_DB_HOST": "127.0.0.1",
        "HEALTHLAKE_DB_PORT": "1",
    }  # connection refused: the error path must not echo the secret
    proc = subprocess.run(
        [sys.executable, "-m", "healthlake.cli", "discover"], env=env, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 4
    assert "Sup3r-Secret-Value" not in proc.stdout + proc.stderr
    last = json.loads(proc.stderr.strip().splitlines()[-1])
    assert last["event"] == "command_finished" and last["exit_code"] == 4 and "duration_ms" in last


def test_verify_bronze_detects_tampering(lake: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    from healthlake.cli import main
    from healthlake.pipelines.runner import store

    assert run(lake["landing"], f.write_csv_batch(lake["landing"], f.business_rows()))["ok"]
    assert main(["verify-bronze"]) == 0
    sha = one("SELECT sha256 FROM bronze.file ORDER BY sha256 LIMIT 1")
    p = store().path(sha)
    p.chmod(0o644)
    p.write_bytes(b"tampered")
    capsys.readouterr()
    assert main(["verify-bronze"]) == 3
    out = json.loads(capsys.readouterr().out)
    assert out["details"]["corrupted"] == [sha]


def test_gc_work_removes_only_finished_processings(lake: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    from healthlake.cli import main

    r = run(lake["landing"], f.write_csv_batch(lake["landing"], f.business_rows()))
    assert (lake["work"] / r["processing_id"]).is_dir()
    (lake["work"] / ("f" * 64)).mkdir()  # unknown/in-progress processing: kept
    capsys.readouterr()
    assert main(["gc-work", "--older-than-hours", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["removed"] == 1
    assert not (lake["work"] / r["processing_id"]).exists()
    assert (lake["work"] / ("f" * 64)).exists()
    # replay after cleanup still succeeds idempotently (steps are already done in the database)
    assert run(lake["landing"], f.write_csv_batch(lake["landing"], f.business_rows()))["status"] == "succeeded"
    assert one("SELECT count(*) FROM ctl.event WHERE event='adapted'") == 1  # nothing was redone
    assert one("SELECT count(*) FROM ctl.event WHERE event='processing_classified'") == 1
