"""API contract, security, pagination and release pinning against a real published release (needs dbt)."""

from __future__ import annotations

import json
import os
import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from tests.conftest import ensure_owner
from tests.fixtures import factory as f

pytestmark = [pytest.mark.db, pytest.mark.slow]


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    admin = os.environ.get("HEALTHLAKE_TEST_ADMIN_DSN")
    if not admin or not os.environ.get("HEALTHLAKE_DBT_BIN"):
        pytest.skip("needs HEALTHLAKE_TEST_ADMIN_DSN and HEALTHLAKE_DBT_BIN")
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("api")
    name = f"hl_test_{uuid.uuid4().hex[:10]}"
    for role in ("owner", "ingest", "dbt", "publish", "api"):
        p = tmp / f"pw_{role}"
        p.write_text(secrets.token_urlsafe(24))
        mp.setenv(f"HEALTHLAKE_DB_{role.upper()}_PASSWORD_FILE", str(p))
    with psycopg.connect(admin, autocommit=True) as conn:
        host, port = conn.info.host, conn.info.port
        ensure_owner(conn, (tmp / "pw_owner").read_text())
        conn.execute(sql.SQL("CREATE DATABASE {} OWNER healthlake_owner").format(sql.Identifier(name)))
    for k in ("landing", "lake", "work", "artifacts"):
        (tmp / k).mkdir()
        mp.setenv(f"HEALTHLAKE_{k.upper()}_DIR", str(tmp / k))
    mp.setenv("HEALTHLAKE_DB_HOST", host)
    mp.setenv("HEALTHLAKE_DB_PORT", str(port))
    mp.setenv("HEALTHLAKE_DB_NAME", name)
    mp.delenv("HEALTHLAKE_HL7_VALIDATOR_JAR", raising=False)
    (tmp / "cursor").write_text(secrets.token_urlsafe(48))
    mp.setenv("HEALTHLAKE_API_CURSOR_SECRET_FILE", str(tmp / "cursor"))
    from healthlake.api import db as apidb
    from healthlake.api import security
    from healthlake.api.security import generate_keys
    from healthlake.db.init import init_database
    from healthlake.ingestion.registry import ensure_sources
    from healthlake.pipelines.runner import sources_config

    generate_keys(tmp / "keys.json", tmp / "keys_plain.json")
    mp.setenv("HEALTHLAKE_API_KEYS_FILE", str(tmp / "keys.json"))
    for fn in (security.load_keys, security._cursor_secret, apidb.engine):
        fn.cache_clear()
    keys = json.loads((tmp / "keys_plain.json").read_text())
    init_database()
    from healthlake.db import connect

    with connect("ingest", autocommit=True) as conn:
        ensure_sources(conn, sources_config()["sources"])
    from fastapi.testclient import TestClient

    from healthlake.api.app import app

    client = TestClient(app)
    yield {"client": client, "keys": keys, "landing": tmp / "landing", "db": name}
    apidb.engine().dispose()
    for fn in (security.load_keys, security._cursor_secret, apidb.engine):
        fn.cache_clear()
    mp.undo()
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def h(env: dict[str, Any], who: str = "dashboard") -> dict[str, str]:
    return {"X-API-Key": env["keys"][who]}


def cycle() -> str:
    from healthlake.release.build import build_release
    from healthlake.release.gate import quality_gate
    from healthlake.release.publish import publish

    rid = build_release()["release_id"]
    quality_gate(rid)
    publish(rid)
    return rid  # type: ignore[no-any-return]


def ingest(landing: Path, bid: str) -> None:
    from tests.integration.helpers import run

    assert run(landing, bid)["ok"]


def test_ordered_scenario(env: dict[str, Any]) -> None:
    """One ordered scenario (module DB): before publication, publication, contract, security, pinning, purge."""
    c: TestClient = env["client"]
    # ---- before any publication
    assert c.get("/health/live").json() == {"status": "ok"}
    r = c.get("/health/ready")
    assert r.status_code == 503 and r.json()["error_code"] == "no_active_release"
    assert c.get("/v1/summary", headers=h(env)).status_code == 503

    ingest(env["landing"], f.write_fhir_batch(env["landing"], f.fhir_population(5, 4)))
    ingest(env["landing"], f.write_csv_batch(env["landing"], f.business_rows(7, 3)))
    ingest(env["landing"], f.write_json_batch(env["landing"], f.business_rows(4, 2)))
    r1 = cycle()

    # ---- health, auth, scopes
    assert c.get("/health/ready").json()["release_id"] == r1
    assert c.get("/v1/summary").status_code == 401
    assert c.get("/v1/summary", headers={"X-API-Key": "hl_dashboard_wrong"}).status_code == 401
    assert c.get("/v1/summary", headers=h(env, "operator")).status_code == 403
    assert c.get("/v1/quality", headers=h(env, "analyst")).status_code == 403
    assert c.get("/metrics", headers=h(env, "analyst")).status_code == 403
    assert c.get("/v1/quality", headers=h(env, "operator")).status_code == 200

    # ---- summary matches Gold
    s = c.get("/v1/summary", headers=h(env)).json()
    assert s["release_id"] == r1 and s["patients"] == 16 and s["encounters"] == 16
    assert s["observations"] == 5 * 4 + 7 * 3 + 4 * 2
    assert s["medication_requests"] == 16 and "synthetic data only" in s["notice"]
    assert sum(x["patients"] for x in s["by_source"]) == 16

    # ---- data minimisation: exact patient fields
    p = c.get("/v1/patients", headers=h(env), params={"limit": 1}).json()["data"][0]
    assert set(p) == {"patient_key", "source_id", "gender", "birth_year", "birth_date_precision", "deceased"}

    # ---- keyset pagination covers everything once, deterministic order
    def collect(path: str, params: dict[str, Any], key: str, limit: int = 3) -> tuple[list[str], set[str]]:
        seen: list[str] = []
        releases: set[str] = set()
        cursor = None
        while True:
            q = {**params, "limit": limit, **({"cursor": cursor} if cursor else {})}
            body = c.get(path, headers=h(env), params=q).json()
            seen += [row[key] for row in body["data"]]
            releases.add(body["release_id"])
            cursor = body["page"]["next_cursor"]
            if not cursor:
                return seen, releases

    keys, _ = collect("/v1/patients", {}, "patient_key")
    assert len(keys) == 16 and len(set(keys)) == 16 and keys == sorted(keys)
    enc, _ = collect("/v1/encounters", {"source_id": "horizon-nord"}, "encounter_key", limit=2)
    assert len(enc) == 7 and len(set(enc)) == 7
    obs, _ = collect("/v1/observations", {"code": "8867-4"}, "observation_key", limit=4)
    assert len(obs) == 7 * 3 + 4 * 2
    vol = c.get("/v1/observations", headers=h(env), params={"group_by": "code"}).json()["data"]
    assert sum(v["observations"] for v in vol) == s["observations"]
    day = c.get("/v1/encounters", headers=h(env), params={"group_by": "day"}).json()["data"]
    assert sum(d["encounters"] for d in day) == 16
    dx = c.get("/v1/diagnoses", headers=h(env)).json()["data"]
    assert [d["conditions"] for d in dx] == sorted((d["conditions"] for d in dx), reverse=True)
    med = c.get("/v1/medication-requests", headers=h(env), params={"code": "860975"}).json()["data"]
    assert len(med) == 5 and med[0]["medication"]["code"] == "860975"
    # an unknown code matches no code key: empty page, not an error
    none = c.get("/v1/observations", headers=h(env), params={"code": "0000-0"}).json()
    assert none["data"] == [] and none["page"]["next_cursor"] is None
    # date range [start, end): central encounters start 2025-03-01T09:00Z
    rng = c.get("/v1/encounters", headers=h(env), params={"start": "2025-03-01T09:00:00Z", "end": "2025-03-02"})
    assert len(rng.json()["data"]) == 5

    # ---- validation errors (422)
    for params in (
        {"limit": 201},
        {"limit": 0},
        {"release_id": "nothex"},
        {"cursor": "abc.def"},
        {"start": "2025-03-02", "end": "2025-03-01"},
        {"source_id": "elsewhere"},
    ):
        resp = c.get("/v1/encounters", headers=h(env), params=params)
        assert resp.status_code == 422, (params, resp.text)
    assert c.get("/v1/diagnoses", headers=h(env), params={"code": "1' OR '1'='1"}).status_code == 422
    page1 = c.get("/v1/patients", headers=h(env), params={"limit": 2}).json()
    cur = page1["page"]["next_cursor"]
    assert (
        c.get(
            "/v1/patients", headers=h(env), params={"limit": 2, "cursor": cur, "source_id": "horizon-sud"}
        ).status_code
        == 422
    )
    body, sig = cur.split(".")
    assert c.get("/v1/patients", headers=h(env), params={"cursor": body + "." + sig[::-1]}).status_code == 422

    # ---- a publication between two pages does not change the dataset being paged
    first = c.get("/v1/patients", headers=h(env), params={"limit": 5}).json()
    # new revision of horizon-nord: the same 7 patients unchanged plus 9 new ones
    ingest(env["landing"], f.write_csv_batch(env["landing"], f.business_rows(16, 3), revision=2))
    r2 = cycle()
    assert r2 != r1
    assert c.get("/v1/summary", headers=h(env)).json()["patients"] == 25
    got = [x["patient_key"] for x in first["data"]]
    cursor = first["page"]["next_cursor"]
    while cursor:
        page = c.get("/v1/patients", headers=h(env), params={"limit": 5, "cursor": cursor}).json()
        assert page["release_id"] == r1
        got += [x["patient_key"] for x in page["data"]]
        cursor = page["page"]["next_cursor"]
    assert len(got) == 16 and len(set(got)) == 16
    # explicit pin
    assert c.get("/v1/summary", headers=h(env), params={"release_id": r1}).json()["patients"] == 16
    rel = c.get("/v1/releases", headers=h(env, "operator")).json()
    assert rel["active_release_id"] == r2 and {x["release_id"] for x in rel["data"]} == {r1, r2}

    # ---- purged release -> 410, unknown -> 404
    from healthlake.db import connect
    from healthlake.release.publish import purge_old_releases

    with connect("publish", autocommit=True) as conn:
        assert purge_old_releases(conn, keep=0) == [r1]
    assert c.get("/v1/summary", headers=h(env), params={"release_id": r1}).status_code == 410
    resp = c.get("/v1/patients", headers=h(env), params={"cursor": first["page"]["next_cursor"], "limit": 5})
    assert resp.status_code == 410
    assert c.get("/v1/summary", headers=h(env), params={"release_id": "0" * 64}).status_code == 404

    # ---- operations
    q = c.get("/v1/quality", headers=h(env)).json()
    assert q["release_id"] == r2 and q["catalog_version"] == "qc-1"
    assert {x["check_id"] for x in q["release_checks"]} >= {"dbt.tests", "release.terminology_coverage"}
    runs = c.get("/v1/pipeline-runs", headers=h(env), params={"limit": 2}).json()
    assert len(runs["data"]) == 2 and runs["page"]["next_cursor"]
    more = c.get("/v1/pipeline-runs", headers=h(env), params={"limit": 2, "cursor": runs["page"]["next_cursor"]})
    assert more.status_code == 200 and len(more.json()["data"]) == 2
    met = c.get("/metrics", headers=h(env)).text
    assert 'healthlake_api_requests_total{method="GET",route="/v1/patients",status="200"}' in met
    assert "healthlake_resources" in met
    assert "synthetic data only" in c.get("/openapi.json").json()["info"]["description"]


def test_database_down_gives_503(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from healthlake.api import db as apidb

    apidb.engine().dispose()
    apidb.engine.cache_clear()
    monkeypatch.setenv("HEALTHLAKE_DB_PORT", "1")
    try:
        r = env["client"].get("/v1/summary", headers=h(env))
        assert r.status_code == 503 and r.json()["error_code"] == "db_unavailable"
        assert env["client"].get("/health/ready").status_code == 503
    finally:
        apidb.engine.cache_clear()
