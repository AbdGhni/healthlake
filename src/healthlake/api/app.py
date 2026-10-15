"""HealthLake analytics API (read-only). Run: uvicorn healthlake.api.app:app"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from sqlalchemy.exc import DBAPIError, OperationalError

from healthlake import DISCLAIMER, __version__
from healthlake.api import db
from healthlake.api import models as m
from healthlake.api.listing import Listing, filters_hash, run_page
from healthlake.api.security import ApiKey, CursorError, authenticate, decode_cursor, encode_cursor
from healthlake.generation.synthea import load_json
from healthlake.metrics import PipelineCollector

DEFAULT_LIMIT, MAX_LIMIT = 50, 200
HEX64 = r"^[0-9a-f]{64}$"

DESCRIPTION = f"""
**{DISCLAIMER}**

Read-only analytics over the active published release (or a pinned `release_id`). Authentication: `X-API-Key`.
Scopes: `read` (analytics), `ops` (quality, pipeline runs, releases, metrics). Lists use keyset pagination with a
signed `cursor` that pins the release of the first page, so a publication between two pages never causes
omissions or repetitions. Dates are UTC; ranges are `[start, end)`.

Errors: 401 missing/invalid key, 403 missing scope, 404 unknown release, 410 purged release,
422 invalid parameter or cursor, 503 database unavailable or nothing published yet.
"""

app = FastAPI(
    title="HealthLake API",
    version=__version__,
    description=DESCRIPTION,
    responses={401: {"model": m.ErrorBody}, 403: {"model": m.ErrorBody}, 503: {"model": m.ErrorBody}},
)

REGISTRY = CollectorRegistry()
REQUESTS = Counter("healthlake_api_requests", "API requests", ["route", "method", "status"], registry=REGISTRY)
LATENCY = Histogram(
    "healthlake_api_request_duration_seconds",
    "API latency",
    ["route", "method"],
    registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
REGISTRY.register(PipelineCollector("api"))


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status, self.code, self.detail = status, code, detail


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail, "error_code": exc.code})


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail), "error_code": "http_error"})


@app.exception_handler(OperationalError)
@app.exception_handler(DBAPIError)
async def _db_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "database unavailable", "error_code": "db_unavailable"})


@app.middleware("http")
async def _metrics_mw(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "unmatched")  # template, bounded cardinality
    LATENCY.labels(route, request.method).observe(time.perf_counter() - start)
    REQUESTS.labels(route, request.method, str(response.status_code)).inc()
    response.headers["X-HealthLake-Notice"] = "synthetic-data-only"
    response.headers["Cache-Control"] = "no-store"
    return response


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require(scope: str) -> Callable[[str | None], ApiKey]:
    def dep(key: Annotated[str | None, Depends(api_key_header)]) -> ApiKey:
        found = authenticate(key)
        if found is None:
            raise ApiError(401, "unauthenticated", "missing or invalid X-API-Key")
        if scope not in found.scopes:
            raise ApiError(403, "forbidden", f"scope '{scope}' required")
        return found

    return dep


Read = Annotated[ApiKey, Depends(require("read"))]
Ops = Annotated[ApiKey, Depends(require("ops"))]


@dataclass(frozen=True)
class Rel:
    release_id: str
    schema: str
    published_at: datetime | None


def _release(release_id: str | None) -> Rel:
    if release_id is None:
        row = db.fetch_one("SELECT release_id FROM ctl.active_release")
        if row is None or row["release_id"] is None:
            raise ApiError(503, "no_active_release", "no release has been published yet")
        release_id = row["release_id"]
    r = db.fetch_one(
        "SELECT release_id, schema_name, status, published_at FROM ctl.release WHERE release_id=:r", {"r": release_id}
    )
    if r is None or r["status"] not in ("published", "purged"):
        raise ApiError(404, "release_not_found", "unknown or unpublished release")
    if r["status"] == "purged":
        raise ApiError(410, "release_purged", "this release was purged by the retention policy")
    return Rel(r["release_id"], r["schema_name"], r["published_at"])


def _utc(v: datetime | date | None) -> datetime | None:
    if v is None:
        return None
    if not isinstance(v, datetime):
        v = datetime(v.year, v.month, v.day)
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def _range(start: datetime | date | None, end: datetime | date | None) -> tuple[datetime | None, datetime | None]:
    s, e = _utc(start), _utc(end)
    if s and e and e <= s:
        raise ApiError(422, "invalid_range", "end must be after start ([start, end) in UTC)")
    return s, e


ReleaseQ = Annotated[str | None, Query(pattern=HEX64, description="Pin a published release (default: active)")]
LimitQ = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
CursorQ = Annotated[str | None, Query(max_length=2048)]
SourceQ = Annotated[m.SourceId | None, Query()]
CodeQ = Annotated[str | None, Query(pattern=r"^[A-Za-z0-9.\-_]{1,64}$")]
StartQ = Annotated[datetime | date | None, Query(description="Inclusive, UTC (naive values are read as UTC)")]
EndQ = Annotated[datetime | date | None, Query(description="Exclusive, UTC")]


def _paged(
    listing: Listing,
    endpoint: str,
    filters: dict[str, Any],
    where: list[str],
    params: dict[str, Any],
    limit: int,
    cursor: str | None,
    release_id: str | None,
    code_col: str | None = None,
) -> dict[str, Any]:
    """One page of a listing. With `code_col`, the `code` filter is resolved to code keys of the release first, so
    that a single key filters on the indexed column and the index returns rows already in keyset order."""
    fh = filters_hash(filters)
    after = None
    if cursor:
        try:
            payload = decode_cursor(cursor)
        except CursorError as exc:
            raise ApiError(422, "invalid_cursor", str(exc)) from None
        if payload.get("e") != endpoint or payload.get("f") != fh:
            raise ApiError(422, "cursor_mismatch", "cursor was issued for another endpoint or other filters")
        if release_id and release_id != payload["r"]:
            raise ApiError(422, "cursor_mismatch", "cursor is pinned to another release")
        release_id, after = payload["r"], payload["k"]
    rel = _release(release_id)
    if code_col and params.get("code"):
        keys = [
            r["code_key"]
            for r in db.fetch_all(
                f"SELECT code_key FROM {db.quote_schema(rel.schema)}.dim_code WHERE code = :code",
                {"code": params["code"]},
            )
        ]
        if len(keys) == 1:
            where = [*where, f"{code_col} = :code_key"]
            params = {**params, "code_key": keys[0]}
        else:
            where = [*where, f"{code_col} = ANY(:code_keys)"]
            params = {**params, "code_keys": keys}
    data, next_key = run_page(listing, rel.schema, where, params, limit, after)
    nxt = encode_cursor({"v": 1, "r": rel.release_id, "e": endpoint, "f": fh, "k": next_key}) if next_key else None
    return {"release_id": rel.release_id, "data": data, "page": {"limit": limit, "next_cursor": nxt}}


# ---------------------------------------------------------------- health
@app.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"], responses={503: {"model": m.ErrorBody}})
def ready() -> dict[str, Any]:
    rel = _release(None)
    return {"status": "ready", "release_id": rel.release_id}


# ---------------------------------------------------------------- releases
@app.get("/v1/releases/current", response_model=m.Release, tags=["releases"])
def current_release(_: Read) -> dict[str, Any]:
    rel = _release(None)
    row = db.fetch_one(
        "SELECT r.release_id, r.status, r.published_at, r.created_at,"
        " (SELECT count(*) FROM ctl.release_processing rp WHERE rp.release_id=r.release_id) AS processings"
        " FROM ctl.release r WHERE r.release_id=:r",
        {"r": rel.release_id},
    )
    assert row is not None
    return {**row, "active": True}


@app.get("/v1/releases", response_model=m.ReleaseList, tags=["releases"])
def releases(_: Ops, limit: LimitQ = DEFAULT_LIMIT) -> dict[str, Any]:
    active = db.fetch_one("SELECT release_id FROM ctl.active_release")
    act = active["release_id"] if active else None
    rows = db.fetch_all(
        "SELECT release_id, status, published_at, created_at FROM ctl.release"
        " ORDER BY created_at DESC, release_id LIMIT :l",
        {"l": limit},
    )
    return {"active_release_id": act, "data": [{**r, "active": r["release_id"] == act} for r in rows]}


# ---------------------------------------------------------------- summary
LIVE_SUMMARY_SQL = (
    "SELECT (SELECT count(*) FROM {s}.dim_patient) AS patients,"
    " (SELECT count(*) FROM {s}.fct_encounter) AS encounters,"
    " (SELECT count(*) FROM {s}.fct_condition) AS conditions,"
    " (SELECT count(*) FROM {s}.agg_diagnosis) AS distinct_diagnosis_codes,"
    " (SELECT count(*) FROM {s}.fct_observation) AS observations,"
    " (SELECT count(*) FROM {s}.fct_observation_component) AS observation_components,"
    " (SELECT count(*) FROM {s}.fct_medication_request) AS medication_requests,"
    " (SELECT min(start_at) FROM {s}.fct_encounter) AS first_encounter_at,"
    " (SELECT max(start_at) FROM {s}.fct_encounter) AS last_encounter_at"
)
LIVE_BREAKDOWN_SQL = (
    "SELECT 'category' AS breakdown, encounter_category AS item, NULL::bigint AS patients, count(*) AS encounters"
    " FROM {s}.fct_encounter GROUP BY 2"
    " UNION ALL SELECT 'source', p.source_id, p.patients, coalesce(e.encounters, 0) FROM"
    " (SELECT source_id, count(*) AS patients FROM {s}.dim_patient GROUP BY 1) p LEFT JOIN"
    " (SELECT source_id, count(*) AS encounters FROM {s}.fct_encounter GROUP BY 1) e USING (source_id)"
    " ORDER BY 1, 2"
)


@app.get("/v1/summary", response_model=m.Summary, tags=["analytics"])
def summary(_: Read, release_id: ReleaseQ = None) -> dict[str, Any]:
    rel = _release(release_id)
    s = db.quote_schema(rel.schema)
    # counts are precomputed per release by dbt (agg_summary, reconciled with the facts by a dbt test);
    # releases built before agg_summary existed are still served, from the facts
    pre = db.fetch_one("SELECT to_regclass(:t) IS NOT NULL AS ok", {"t": f"{rel.schema}.agg_summary"})
    row = db.fetch_one(f"SELECT * FROM {s}.agg_summary" if pre and pre["ok"] else LIVE_SUMMARY_SQL.format(s=s))
    assert row is not None
    parts = db.fetch_all(
        f"SELECT breakdown, item, patients, encounters FROM {s}.agg_summary_breakdown ORDER BY 1, 2"
        if pre and pre["ok"]
        else LIVE_BREAKDOWN_SQL.format(s=s)
    )
    cats = [{"encounter_category": p["item"], "n": p["encounters"]} for p in parts if p["breakdown"] == "category"]
    by_source = [
        {"source_id": p["item"], "patients": p["patients"], "encounters": p["encounters"]}
        for p in parts
        if p["breakdown"] == "source"
    ]
    return {
        "release_id": rel.release_id,
        "published_at": rel.published_at,
        "notice": DISCLAIMER,
        **row,
        "encounters_by_category": {c["encounter_category"]: c["n"] for c in cats},
        "by_source": by_source,
    }


# ---------------------------------------------------------------- patients
PATIENTS = Listing(
    "patients",
    "{schema}.dim_patient p",
    [
        "p.patient_key::text AS patient_key",
        "p.source_id",
        "p.gender",
        "p.birth_year",
        "p.birth_date_precision",
        "p.deceased",
    ],
    ["p.patient_key"],
    ["uuid"],
)


@app.get("/v1/patients", response_model=m.Page[m.Patient], tags=["analytics"])
def patients(
    _: Read,
    source_id: SourceQ = None,
    gender: Annotated[Literal["male", "female", "other", "unknown"] | None, Query()] = None,
    limit: LimitQ = DEFAULT_LIMIT,
    cursor: CursorQ = None,
    release_id: ReleaseQ = None,
) -> dict[str, Any]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if source_id:
        where.append("p.source_id = :source_id")
        params["source_id"] = source_id
    if gender:
        where.append("p.gender = :gender")
        params["gender"] = gender
    return _paged(
        PATIENTS, "patients", {"source_id": source_id, "gender": gender}, where, params, limit, cursor, release_id
    )


# ---------------------------------------------------------------- encounters
ENCOUNTERS = Listing(
    "encounters",
    "{schema}.fct_encounter e LEFT JOIN {schema}.dim_code c ON c.code_key = e.type_code_key",
    [
        "e.encounter_key::text AS encounter_key",
        "e.patient_key::text AS patient_key",
        "e.source_id",
        "e.status",
        "e.class_code",
        "e.encounter_category",
        "c.system AS type_system",
        "c.code AS type_code",
        "c.display AS type_display",
        "e.start_at",
        "e.end_at",
        "e.duration_minutes",
    ],
    ["coalesce(e.start_at, '-infinity'::timestamptz)", "e.encounter_key"],
    ["timestamptz", "uuid"],
)
ACTIVITY = Listing(
    "activity",
    "{schema}.agg_activity_daily a",
    ["a.activity_date", "a.source_id", "a.encounter_category", "a.encounters", "a.distinct_patients"],
    ["a.activity_date", "a.source_id", "a.encounter_category"],
    ["date", "text", "text"],
)
Category = Literal["ambulatory", "inpatient", "emergency", "observation", "virtual", "home_health", "other"]


@app.get(
    "/v1/encounters",
    tags=["analytics"],
    response_model=m.Page[m.Encounter] | m.Page[m.ActivityDay],
    description="`group_by=day` returns daily activity (agg_activity_daily) instead of encounter rows.",
)
def encounters(
    _: Read,
    source_id: SourceQ = None,
    category: Annotated[Category | None, Query()] = None,
    patient_key: Annotated[UUID | None, Query()] = None,
    start: StartQ = None,
    end: EndQ = None,
    group_by: Annotated[Literal["none", "day"], Query()] = "none",
    limit: LimitQ = DEFAULT_LIMIT,
    cursor: CursorQ = None,
    release_id: ReleaseQ = None,
) -> dict[str, Any]:
    s, e = _range(start, end)
    filters = {
        "source_id": source_id,
        "category": category,
        "patient_key": patient_key,
        "start": s,
        "end": e,
        "group_by": group_by,
    }
    where: list[str] = []
    params: dict[str, Any] = {}
    if group_by == "day":
        if patient_key:
            raise ApiError(422, "invalid_filter", "patient_key cannot be used with group_by=day")
        for col, val in (("a.source_id", source_id), ("a.encounter_category", category)):
            if val:
                where.append(f"{col} = :{col.split('.')[1]}")
                params[col.split(".")[1]] = val
        if s:
            where.append("a.activity_date >= CAST(:start AS date)")
            params["start"] = s.date()
        if e:
            where.append("a.activity_date < CAST(:end AS date)")
            params["end"] = e.date()
        return _paged(ACTIVITY, "encounters:day", filters, where, params, limit, cursor, release_id)
    eq_filters: list[tuple[str, str, Any]] = [
        ("e.source_id", "source_id", source_id),
        ("e.encounter_category", "category", category),
        ("e.patient_key", "patient_key", patient_key),
    ]
    for col, key, val in eq_filters:
        if val:
            where.append(f"{col} = :{key}")
            params[key] = val
    if s:
        where.append("e.start_at >= :start")
        params["start"] = s
    if e:
        where.append("e.start_at < :end")
        params["end"] = e
    page = _paged(ENCOUNTERS, "encounters", filters, where, params, limit, cursor, release_id)
    for r in page["data"]:
        code = {"system": r.pop("type_system"), "code": r.pop("type_code"), "display": r.pop("type_display")}
        r["type"] = code if code["code"] else None
    return page


# ---------------------------------------------------------------- diagnoses
DIAGNOSES = Listing(
    "diagnoses",
    "{schema}.agg_diagnosis d",
    [
        "d.code_key",
        "d.system",
        "d.system_label",
        "d.code",
        "d.display",
        "d.conditions",
        "d.distinct_patients",
        "d.first_onset_at",
        "d.last_onset_at",
    ],
    ["-d.conditions", "d.code_key"],
    ["bigint", "text"],
)


@app.get(
    "/v1/diagnoses",
    response_model=m.Page[m.Diagnosis],
    tags=["analytics"],
    description="Diagnosis codes ordered by number of conditions (descending).",
)
def diagnoses(
    _: Read,
    system_label: Annotated[Literal["SNOMED CT", "LOINC", "RxNorm", "other", "no system"] | None, Query()] = None,
    code: CodeQ = None,
    limit: LimitQ = DEFAULT_LIMIT,
    cursor: CursorQ = None,
    release_id: ReleaseQ = None,
) -> dict[str, Any]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if system_label:
        where.append("d.system_label = :system_label")
        params["system_label"] = system_label
    if code:
        where.append("d.code = :code")
        params["code"] = code
    return _paged(
        DIAGNOSES, "diagnoses", {"system_label": system_label, "code": code}, where, params, limit, cursor, release_id
    )


# ---------------------------------------------------------------- observations
OBSERVATIONS = Listing(
    "observations",
    "{schema}.fct_observation o JOIN {schema}.dim_code c ON c.code_key = o.code_key"
    " LEFT JOIN {schema}.dim_code v ON v.code_key = o.value_code_key",
    [
        "o.observation_key::text AS observation_key",
        "o.patient_key::text AS patient_key",
        "o.encounter_key::text AS encounter_key",
        "o.source_id",
        "o.status",
        "o.category_code",
        "c.system AS c_system",
        "c.code AS c_code",
        "c.display AS c_display",
        "o.effective_at",
        "o.effective_precision",
        "o.value_type",
        "o.value_numeric::float8 AS value_numeric",
        "o.value_unit_code",
        "o.value_string",
        "o.value_boolean",
        "v.system AS v_system",
        "v.code AS v_code",
        "v.display AS v_display",
        "o.data_absent_reason",
        "o.component_count",
    ],
    ["coalesce(o.effective_at, '-infinity'::timestamptz)", "o.observation_key"],
    ["timestamptz", "uuid"],
)
OBS_VOLUME = Listing(
    "observation_volume",
    "{schema}.agg_observation_volume a",
    [
        "a.code_key",
        "a.system",
        "a.code",
        "a.display",
        "a.value_type",
        "a.value_unit_code",
        "a.observations",
        "a.numeric_values",
        "a.absent_values",
        "a.distinct_patients",
        "a.min_value::float8 AS min_value",
        "a.mean_value::float8 AS mean_value",
        "a.max_value::float8 AS max_value",
    ],
    ["-a.observations", "a.code_key", "a.value_type", "coalesce(a.value_unit_code, '')"],
    ["bigint", "text", "text", "text"],
)


@app.get(
    "/v1/observations",
    tags=["analytics"],
    response_model=m.Page[m.Observation] | m.Page[m.ObservationVolume],
    description="Observation rows, or with `group_by=code` volumes per (code, value type, unit). "
    "Statistics never mix codes or units.",
)
def observations(
    _: Read,
    code: CodeQ = None,
    source_id: SourceQ = None,
    patient_key: Annotated[UUID | None, Query()] = None,
    category: Annotated[str | None, Query(pattern=r"^[a-z\-]{1,40}$")] = None,
    start: StartQ = None,
    end: EndQ = None,
    group_by: Annotated[Literal["none", "code"], Query()] = "none",
    limit: LimitQ = DEFAULT_LIMIT,
    cursor: CursorQ = None,
    release_id: ReleaseQ = None,
) -> dict[str, Any]:
    s, e = _range(start, end)
    filters = {
        "code": code,
        "source_id": source_id,
        "patient_key": patient_key,
        "category": category,
        "start": s,
        "end": e,
        "group_by": group_by,
    }
    where: list[str] = []
    params: dict[str, Any] = {}
    if group_by == "code":
        if patient_key or source_id or category or s or e:
            raise ApiError(422, "invalid_filter", "group_by=code supports only the code filter")
        if code:
            where.append("a.code = :code")
            params["code"] = code
        return _paged(OBS_VOLUME, "observations:code", filters, where, params, limit, cursor, release_id)
    if code:
        params["code"] = code  # resolved to code keys in _paged
    for col, key, val in (
        ("o.source_id", "source_id", source_id),
        ("o.patient_key", "patient_key", patient_key),
        ("o.category_code", "category", category),
    ):
        if val:
            where.append(f"{col} = :{key}")
            params[key] = val
    if s:
        where.append("o.effective_at >= :start")
        params["start"] = s
    if e:
        where.append("o.effective_at < :end")
        params["end"] = e
    page = _paged(OBSERVATIONS, "observations", filters, where, params, limit, cursor, release_id, "o.code_key")
    for r in page["data"]:
        r["code"] = {"system": r.pop("c_system"), "code": r.pop("c_code"), "display": r.pop("c_display")}
        v = {"system": r.pop("v_system"), "code": r.pop("v_code"), "display": r.pop("v_display")}
        r["value_code"] = v if v["code"] else None
    return page


# ---------------------------------------------------------------- medication requests
MEDS = Listing(
    "medication_requests",
    "{schema}.fct_medication_request r LEFT JOIN {schema}.dim_code c ON c.code_key = r.medication_code_key",
    [
        "r.medication_request_key::text AS medication_request_key",
        "r.patient_key::text AS patient_key",
        "r.encounter_key::text AS encounter_key",
        "r.source_id",
        "r.status",
        "r.intent",
        "r.authored_at",
        "c.system AS m_system",
        "c.code AS m_code",
        "c.display AS m_display",
    ],
    ["coalesce(r.authored_at, '-infinity'::timestamptz)", "r.medication_request_key"],
    ["timestamptz", "uuid"],
)


@app.get("/v1/medication-requests", response_model=m.Page[m.MedicationRequest], tags=["analytics"])
def medication_requests(
    _: Read,
    code: CodeQ = None,
    source_id: SourceQ = None,
    patient_key: Annotated[UUID | None, Query()] = None,
    status: Annotated[
        Literal["active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft", "unknown"]
        | None,
        Query(),
    ] = None,
    start: StartQ = None,
    end: EndQ = None,
    limit: LimitQ = DEFAULT_LIMIT,
    cursor: CursorQ = None,
    release_id: ReleaseQ = None,
) -> dict[str, Any]:
    s, e = _range(start, end)
    where: list[str] = []
    params: dict[str, Any] = {}
    if code:
        params["code"] = code  # resolved to code keys in _paged
    for col, key, val in (
        ("r.source_id", "source_id", source_id),
        ("r.patient_key", "patient_key", patient_key),
        ("r.status", "status", status),
    ):
        if val:
            where.append(f"{col} = :{key}")
            params[key] = val
    if s:
        where.append("r.authored_at >= :start")
        params["start"] = s
    if e:
        where.append("r.authored_at < :end")
        params["end"] = e
    filters = {"code": code, "source_id": source_id, "patient_key": patient_key, "status": status, "start": s, "end": e}
    page = _paged(
        MEDS, "medication-requests", filters, where, params, limit, cursor, release_id, "r.medication_code_key"
    )
    for r in page["data"]:
        med = {"system": r.pop("m_system"), "code": r.pop("m_code"), "display": r.pop("m_display")}
        r["medication"] = med if med["code"] else None
    return page


# ---------------------------------------------------------------- quality & operations
@app.get("/v1/quality", response_model=m.Quality, tags=["operations"])
def quality(_: Ops, release_id: ReleaseQ = None) -> dict[str, Any]:
    rel = _release(release_id)
    s = db.quote_schema(rel.schema)
    checks = db.fetch_all(
        "SELECT check_id, status, observed::float8 AS observed, threshold::float8 AS threshold,"
        " details FROM quality.check_result WHERE scope='release' AND scope_id=:r ORDER BY check_id",
        {"r": rel.release_id},
    )
    procs = db.fetch_all(
        f"SELECT processing_id, source_id, source_revision, received, accepted, deduplicated,"
        f" rejected, out_of_scope, reject_rate_new::float8 AS reject_rate_new, fatal_issues,"
        f" error_issues, warning_issues FROM {s}.agg_quality ORDER BY source_id, source_revision"
    )
    issues = db.fetch_all(
        "SELECT i.check_id, i.severity, count(*) AS issues FROM quality.issue i JOIN ctl.release_processing rp"
        " ON rp.processing_id = i.processing_id WHERE rp.release_id=:r GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2",
        {"r": rel.release_id},
    )
    return {
        "release_id": rel.release_id,
        "catalog_version": load_json("quality-catalog.json")["version"],
        "release_checks": checks,
        "processings": procs,
        "issues": issues,
    }


PIPELINE_RUNS = Listing(
    "pipeline_runs",
    "ctl.attempt a JOIN ctl.processing p USING (processing_id) JOIN ctl.batch b ON b.batch_id = p.batch_id",
    [
        "a.attempt_id::text AS attempt_id",
        "a.orchestrator_run_id",
        "b.source_id",
        "b.source_revision",
        "b.batch_id",
        "a.processing_id",
        "a.status",
        "p.status AS processing_status",
        "a.current_step",
        "a.error_code",
        "a.started_at",
        "a.finished_at",
        "extract(epoch from a.finished_at - a.started_at)::float8 AS duration_seconds",
        "(p.counters->>'received')::bigint AS received",
        "(p.counters->>'accepted')::bigint AS accepted",
        "(p.counters->>'rejected')::bigint AS rejected",
    ],
    ["-extract(epoch from a.started_at)", "a.attempt_id"],
    ["numeric", "uuid"],
)


@app.get(
    "/v1/pipeline-runs",
    response_model=m.Page[m.PipelineRun],
    tags=["operations"],
    description="Ingestion attempts, most recent first. Not tied to a release; `release_id` is the active one.",
)
def pipeline_runs(
    _: Ops,
    source_id: SourceQ = None,
    status: Annotated[Literal["running", "succeeded", "failed", "blocked"] | None, Query()] = None,
    limit: LimitQ = DEFAULT_LIMIT,
    cursor: CursorQ = None,
) -> dict[str, Any]:
    where: list[str] = []
    params: dict[str, Any] = {}
    for col, key, val in (("b.source_id", "source_id", source_id), ("a.status", "status", status)):
        if val:
            where.append(f"{col} = :{key}")
            params[key] = val
    fh = filters_hash({"source_id": source_id, "status": status})
    after = None
    if cursor:
        try:
            payload = decode_cursor(cursor)
        except CursorError as exc:
            raise ApiError(422, "invalid_cursor", str(exc)) from None
        if payload.get("e") != "pipeline-runs" or payload.get("f") != fh:
            raise ApiError(422, "cursor_mismatch", "cursor was issued for another endpoint or other filters")
        after = payload["k"]
    active = db.fetch_one("SELECT release_id FROM ctl.active_release")
    from healthlake.api import listing as lst

    data, next_key = lst.run_page(PIPELINE_RUNS, "release_0000000000000000", where, params, limit, after)
    nxt = encode_cursor({"v": 1, "r": None, "e": "pipeline-runs", "f": fh, "k": next_key}) if next_key else None
    return {
        "release_id": (active or {}).get("release_id") or "",
        "data": data,
        "page": {"limit": limit, "next_cursor": nxt},
    }


@app.get(
    "/metrics",
    tags=["operations"],
    response_class=Response,
    description="Prometheus metrics: API latency and status codes, pipeline and quality gauges.",
)
def metrics(_: Ops) -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
