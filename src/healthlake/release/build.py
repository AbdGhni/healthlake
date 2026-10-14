"""build-release: deterministic snapshot + dbt build in an isolated candidate schema.

Full rebuild of Gold for every release (no incremental shortcuts). The release id is a hash of the
sorted processing ids and the code version, so the same inputs always give the same release.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from healthlake.config import db_config, paths, secret
from healthlake.db import connect
from healthlake.errors import ContractError, HealthLakeError, TransientError
from healthlake.ids import CODE_VERSION, MAPPING_VERSION, VALIDATION_VERSION, release_id, release_schema
from healthlake.observability import log_event, set_context
from healthlake.testing import crashpoint

REPO_ROOT = Path(__file__).resolve().parents[3]
REQUIRED_MODELS = [
    "dim_patient",
    "dim_organization",
    "dim_practitioner",
    "dim_code",
    "dim_date",
    "fct_encounter",
    "fct_condition",
    "fct_observation",
    "fct_observation_component",
    "fct_medication_request",
    "bridge_encounter_practitioner",
    "agg_activity_daily",
    "agg_diagnosis",
    "agg_observation_volume",
    "agg_quality",
]


def dbt_project_dir() -> Path:
    return Path(os.environ.get("HEALTHLAKE_DBT_PROJECT_DIR", REPO_ROOT / "dbt"))


def build_fingerprint() -> tuple[str, dict[str, Any]]:
    """Hash of the dbt project files plus build options, so a changed model gives a new release id."""
    h = hashlib.sha256()
    root = dbt_project_dir()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not rel.startswith(("target/", "logs/", "dbt_packages/")) and "/." not in "/" + rel:
            h.update(rel.encode() + b"\0" + p.read_bytes() + b"\0")
    options = {"inject_gate_failure": os.environ.get("HEALTHLAKE_INJECT_GATE_FAILURE") == "1"}
    h.update(json.dumps(options, sort_keys=True).encode())
    return h.hexdigest(), options


def release_artifacts_dir(rid: str) -> Path:
    return paths().artifacts / "releases" / rid


def candidate_processings(conn: psycopg.Connection, must_include: str | None) -> list[str]:
    rows = conn.execute(
        "SELECT processing_id FROM ctl.processing WHERE status='loaded' AND code_version=%s AND mapping_version=%s"
        " AND validation_version=%s ORDER BY processing_id",
        (CODE_VERSION, MAPPING_VERSION, VALIDATION_VERSION),
    ).fetchall()
    pids = [r[0] for r in rows]
    if must_include and must_include not in pids:
        raise ContractError("processing is not loaded with the current code version", code="processing_not_loaded")
    if not pids:
        raise ContractError("no loaded processing to release", code="nothing_to_release")
    return pids


def build_snapshot(conn: psycopg.Connection, rid: str, pids: list[str]) -> dict[str, int]:
    """One member per identity: the version from the highest source_revision among the release processings."""
    with conn.transaction():
        conn.execute("DELETE FROM silver.snapshot_reference WHERE snapshot_id=%s", (rid,))
        conn.execute("DELETE FROM silver.snapshot_member WHERE snapshot_id=%s", (rid,))
        conn.execute(
            "INSERT INTO silver.snapshot_member (snapshot_id, entity_id, resource_version_id, resource_type)"
            " SELECT DISTINCT ON (pr.entity_id) %s, pr.entity_id, pr.resource_version_id, rv.resource_type"
            " FROM silver.processing_resource pr JOIN silver.resource_version rv USING (resource_version_id)"
            " WHERE pr.processing_id = ANY(%s)"
            " ORDER BY pr.entity_id, pr.source_revision DESC, pr.processing_id",
            (rid, pids),
        )
        conn.execute(
            "INSERT INTO silver.snapshot_reference (snapshot_id, from_entity_id, path, to_entity_id)"
            " SELECT sm.snapshot_id, sm.entity_id, r.path, r.target_entity_id FROM silver.snapshot_member sm"
            " JOIN silver.reference r USING (resource_version_id)"
            " WHERE sm.snapshot_id=%s AND r.target_entity_id IS NOT NULL",
            (rid,),
        )
        members = conn.execute("SELECT count(*) FROM silver.snapshot_member WHERE snapshot_id=%s", (rid,)).fetchone()
        dangling = conn.execute(
            "SELECT count(*) FROM silver.snapshot_reference r WHERE r.snapshot_id=%s AND NOT EXISTS"
            " (SELECT 1 FROM silver.snapshot_member m"
            "  WHERE m.snapshot_id=r.snapshot_id AND m.entity_id=r.to_entity_id)",
            (rid,),
        ).fetchone()
    return {"members": members[0] if members else 0, "dangling_references": dangling[0] if dangling else 0}


def _dbt_env(schema: str) -> dict[str, str]:
    cfg = db_config("dbt")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DBT_")}
    env.update(
        {
            "DBT_HOST": cfg.host,
            "DBT_PORT": str(cfg.port),
            "DBT_USER": cfg.user,
            "DBT_DBNAME": cfg.dbname,
            "DBT_SCHEMA": schema,
            "DBT_PASSWORD": secret("HEALTHLAKE_DB_DBT_PASSWORD", required=False) or "",
            "DBT_PROFILES_DIR": str(dbt_project_dir()),
            "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
            "DO_NOT_TRACK": "1",
        }
    )
    return env


def run_dbt(
    args: list[str], schema: str, target_path: Path, rid: str, snapshot_id: str, options: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    dbt = os.environ.get("HEALTHLAKE_DBT_BIN", "dbt")
    variables = json.dumps({"snapshot_id": snapshot_id, "release_id": rid, **options})
    cmd = [
        dbt,
        *args,
        "--project-dir",
        str(dbt_project_dir()),
        "--target-path",
        str(target_path),
        "--vars",
        variables,
        "--log-format",
        "json",
        "--log-path",
        str(target_path / "logs"),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, env=_dbt_env(schema), timeout=3600, check=False)


def _git_version() -> str:
    v = os.environ.get("HEALTHLAKE_GIT_VERSION")
    if v:
        return v
    try:
        res = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "describe", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return res.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def build_release(must_include: str | None = None) -> dict[str, Any]:
    with connect("ingest", autocommit=True) as conn:
        pids = candidate_processings(conn, must_include)
        fingerprint, options = build_fingerprint()
        rid = release_id(pids, build=fingerprint)
        schema = release_schema(rid)
        set_context(release_id=rid)
        row = conn.execute("SELECT status FROM ctl.release WHERE release_id=%s", (rid,)).fetchone()
        if row and row[0] in ("built", "gate_passed", "gate_failed", "published"):
            return {"release_id": rid, "schema": schema, "status": row[0], "idempotent": True, "processings": len(pids)}
        if row and row[0] == "purged":
            raise ContractError("release was purged; rebuild requires new inputs", code="release_purged")
        params = {
            "processings": pids,
            "mapping_version": MAPPING_VERSION,
            "validation_version": VALIDATION_VERSION,
            "git_version": _git_version(),
        }
        with conn.transaction():
            conn.execute(
                "INSERT INTO ctl.release (release_id, schema_name, status, code_version, params)"
                " VALUES (%s,%s,'building',%s,%s) ON CONFLICT (release_id) DO UPDATE SET status='building',"
                " status_reason=NULL",
                (rid, schema, CODE_VERSION, Jsonb(params)),
            )
            for pid in pids:
                conn.execute("INSERT INTO ctl.release_processing VALUES (%s,%s) ON CONFLICT DO NOTHING", (rid, pid))
            log_event("release_building", conn=conn, release_id=rid, payload={"processings": len(pids)})
        snap = build_snapshot(conn, rid, pids)
    out_dir = release_artifacts_dir(rid)
    target = out_dir / "dbt-target"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    build = run_dbt(["build"], schema, target, rid, rid, options)
    crashpoint("during_dbt")
    results = _summarize(target / "run_results.json")
    docs = run_dbt(["docs", "generate"], schema, target, rid, rid, options) if results["model_errors"] == 0 else None
    for name in ("manifest.json", "run_results.json", "catalog.json", "index.html"):
        if (target / name).exists():
            shutil.copy2(target / name, out_dir / name)
    meta = {
        "release_id": rid,
        "schema": schema,
        "snapshot": snap,
        "dbt": results,
        "params": params,
        "dbt_build_exit": build.returncode,
        "dbt_docs_exit": docs.returncode if docs else None,
    }
    (out_dir / "release.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    with connect("ingest", autocommit=True) as conn, conn.transaction():
        if results["model_errors"] or not results["present"]:
            reason = "dbt models failed" if results["present"] else f"dbt did not run: {build.stderr[-300:]}"
            conn.execute("UPDATE ctl.release SET status='failed', status_reason=%s WHERE release_id=%s", (reason, rid))
            log_event("release_failed", level="error", conn=conn, release_id=rid, payload=results)
            if not results["present"]:
                raise TransientError(reason, code="dbt_unavailable", release_id=rid)
            raise HealthLakeError(reason, code="dbt_failed", release_id=rid, **results)
        conn.execute(
            "UPDATE ctl.release SET status='built', built_at=now(), params = params || %s WHERE release_id=%s",
            (Jsonb({"snapshot": snap, "dbt": results}), rid),
        )
        log_event("release_built", conn=conn, release_id=rid, payload={**snap, **results})
    return {"release_id": rid, "schema": schema, "status": "built", "snapshot": snap, "dbt": results}


def _summarize(run_results: Path) -> dict[str, Any]:
    if not run_results.exists():
        return {"present": False, "model_errors": 0, "tests_failed": 0, "tests_passed": 0, "models": 0}
    data = json.loads(run_results.read_text())
    out = {
        "present": True,
        "model_errors": 0,
        "tests_failed": 0,
        "tests_passed": 0,
        "tests_warned": 0,
        "models": 0,
        "seeds": 0,
        "skipped": 0,
        "dbt_version": data.get("metadata", {}).get("dbt_version"),
    }
    for r in data.get("results", []):
        uid, status = r["unique_id"], r["status"]
        if uid.startswith("test."):
            if status == "pass":
                out["tests_passed"] += 1
            elif status == "warn":
                out["tests_warned"] += 1
            elif status == "skipped":
                out["skipped"] += 1
            else:
                out["tests_failed"] += 1
        elif uid.startswith(("model.", "seed.")):
            key = "models" if uid.startswith("model.") else "seeds"
            if status == "success":
                out[key] += 1
            elif status == "skipped":
                out["skipped"] += 1
            else:
                out["model_errors"] += 1
    return out
