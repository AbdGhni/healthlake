"""Snapshot, dbt build, release gate and atomic publication (needs dbt: HEALTHLAKE_DBT_BIN)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from healthlake.errors import QualityBlockedError
from healthlake.release.build import build_release
from healthlake.release.gate import quality_gate
from healthlake.release.publish import publish
from healthlake.testing import InjectedCrashError
from tests.fixtures import factory as f
from tests.integration.helpers import one, run

pytestmark = [pytest.mark.db, pytest.mark.slow]


@pytest.fixture
def dbt_lake(lake: dict[str, Path]) -> dict[str, Path]:
    if not os.environ.get("HEALTHLAKE_DBT_BIN"):
        pytest.skip("HEALTHLAKE_DBT_BIN not set")
    return lake


def active() -> str | None:
    return one("SELECT release_id FROM ctl.active_release")  # type: ignore[no-any-return]


def release_cycle() -> str:
    rid = build_release()["release_id"]
    quality_gate(rid)
    publish(rid)
    return rid  # type: ignore[no-any-return]


def ingest_all(landing: Path, revision: int = 1, n: int = 3) -> None:
    for b in (
        f.write_fhir_batch(landing, f.fhir_population(n), revision=revision),
        f.write_csv_batch(landing, f.business_rows(n), revision=revision),
        f.write_json_batch(landing, f.business_rows(n), revision=revision),
    ):
        assert run(landing, b)["ok"]


def test_happy_path_publish_rebuild_and_switch(dbt_lake: dict[str, Path]) -> None:
    ingest_all(dbt_lake["landing"])
    r1 = release_cycle()
    schema = one("SELECT schema_name FROM ctl.release WHERE release_id=%s", r1)
    assert active() == r1
    assert one(f'SELECT count(*) FROM "{schema}".dim_patient') == 9
    assert one(f'SELECT count(*) FROM "{schema}".fct_encounter') == 9
    assert one(f'SELECT sum(conditions) FROM "{schema}".agg_diagnosis') == 9
    art = dbt_lake["artifacts"] / "releases" / r1
    for name in ("manifest.json", "run_results.json", "catalog.json", "index.html", "release.json"):
        assert (art / name).exists(), name
    # same inputs -> same release id, nothing rebuilt
    again = build_release()
    assert again["release_id"] == r1 and again.get("idempotent")
    # a new revision gives a new release; the previous one stays published and readable
    rows = f.business_rows(3)
    rows["patients.csv"][0]["gender"] = "male"
    assert run(dbt_lake["landing"], f.write_csv_batch(dbt_lake["landing"], rows, revision=2))["ok"]
    r2 = release_cycle()
    assert r2 != r1 and active() == r2
    assert one("SELECT status FROM ctl.release WHERE release_id=%s", r1) == "published"
    assert one(f'SELECT count(*) FROM "{schema}".dim_patient') == 9
    s2 = one("SELECT schema_name FROM ctl.release WHERE release_id=%s", r2)
    # the changed patient appears once, with its latest version
    assert one(f"SELECT count(*) FROM \"{s2}\".dim_patient WHERE source_id='horizon-nord' AND gender='male'") == 1
    assert one(f'SELECT count(*) FROM "{s2}".dim_patient') == 9
    # runbook rollback: re-activating an earlier published release is atomic and allowed
    assert publish(r1)["active"] is True and active() == r1
    assert publish(r2)["active"] is True and active() == r2


def test_failed_gate_keeps_previous_release_active(dbt_lake: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    ingest_all(dbt_lake["landing"])
    r1 = release_cycle()
    monkeypatch.setenv("HEALTHLAKE_INJECT_GATE_FAILURE", "1")
    bad = build_release()["release_id"]
    assert bad != r1
    with pytest.raises(QualityBlockedError):
        quality_gate(bad)
    with pytest.raises(QualityBlockedError):
        publish(bad)
    assert active() == r1
    assert one("SELECT status FROM ctl.release WHERE release_id=%s", bad) == "gate_failed"
    assert (
        one(
            "SELECT status FROM quality.check_result WHERE scope='release' AND scope_id=%s AND check_id='dbt.tests'",
            bad,
        )
        == "fail"
    )


def test_blocked_processing_does_not_change_active_release(dbt_lake: dict[str, Path]) -> None:
    ingest_all(dbt_lake["landing"])
    r1 = release_cycle()
    rows = f.business_rows(1, 2)
    rows["patients.csv"][0]["gender"] = "dragon"  # invalid update of an existing identity
    r = run(dbt_lake["landing"], f.write_csv_batch(dbt_lake["landing"], rows, revision=2))
    assert not r["ok"]
    assert build_release()["release_id"] == r1  # blocked processing is not a release input
    assert active() == r1


@pytest.mark.parametrize("point", ["during_dbt", "after_gate_before_publish"])
def test_release_crash_points_recover(dbt_lake: dict[str, Path], monkeypatch: pytest.MonkeyPatch, point: str) -> None:
    ingest_all(dbt_lake["landing"], n=2)
    monkeypatch.setenv("HEALTHLAKE_CRASH_AT", point)
    with pytest.raises(InjectedCrashError):
        rid = build_release()["release_id"]
        quality_gate(rid)
    assert active() is None  # nothing partially published
    monkeypatch.delenv("HEALTHLAKE_CRASH_AT")
    rid = build_release()["release_id"]
    quality_gate(rid)
    publish(rid)
    assert active() == rid
    assert one("SELECT count(*) FROM ctl.release") == 1


def test_hard_kill_after_publish_commit(dbt_lake: dict[str, Path]) -> None:
    ingest_all(dbt_lake["landing"], n=2)
    rid = build_release()["release_id"]
    quality_gate(rid)
    env = {**os.environ, "HEALTHLAKE_CRASH_AT": "after_publish_commit_before_return", "HEALTHLAKE_CRASH_MODE": "exit"}
    proc = subprocess.run(
        [sys.executable, "-m", "healthlake.cli", "publish", "--release-id", rid],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 137 and proc.stdout == ""
    assert active() == rid  # committed before the crash
    res = publish(rid)
    assert res.get("idempotent") is True


def test_retention_purges_old_schemas(dbt_lake: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTHLAKE_RELEASE_RETENTION", "0")
    ingest_all(dbt_lake["landing"], n=1)
    r1 = release_cycle()
    rows = f.business_rows(1)
    rows["patients.csv"][0]["gender"] = "male"
    assert run(dbt_lake["landing"], f.write_csv_batch(dbt_lake["landing"], rows, revision=2))["ok"]
    r2 = release_cycle()
    assert one("SELECT status FROM ctl.release WHERE release_id=%s", r1) == "purged"
    s1 = one("SELECT schema_name FROM ctl.release WHERE release_id=%s", r1)
    assert one("SELECT count(*) FROM pg_namespace WHERE nspname=%s", s1) == 0
    assert active() == r2


def test_release_records_non_blocking_observations(dbt_lake: dict[str, Path]) -> None:
    ingest_all(dbt_lake["landing"], n=2)
    rid = build_release()["release_id"]
    res = quality_gate(rid)
    obs = res["observations"]
    assert set(obs) == {
        "release.terminology_coverage",
        "release.freshness_clinical_data",
        "release.completeness_encounter_end",
        "release.completeness_observation_effective",
    }
    assert obs["release.terminology_coverage"]["status"] == "pass"
    assert obs["release.completeness_encounter_end"]["observed"] == 1.0
    assert one("SELECT count(*) FROM quality.check_result WHERE scope='release' AND scope_id=%s", rid) == 10
