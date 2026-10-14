"""API client with release pinning and caching keyed by (path, params including release_id)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import streamlit as st

TIMEOUT = httpx.Timeout(10.0, connect=3.0)


class ApiProblemError(Exception):
    """A problem worth showing to the user in plain words."""

    def __init__(self, title: str, detail: str, status: int | None = None) -> None:
        super().__init__(title)
        self.title, self.detail, self.status = title, detail, status


def _base_url() -> str:
    return os.environ.get("HEALTHLAKE_API_URL", "http://api:8000").rstrip("/")


def _key() -> str:
    path = os.environ.get("HEALTHLAKE_DASHBOARD_API_KEY_FILE")
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8").strip()
    key = os.environ.get("HEALTHLAKE_DASHBOARD_API_KEY")
    if not key:
        raise ApiProblemError("Dashboard not configured", "No API key: set HEALTHLAKE_DASHBOARD_API_KEY_FILE.")
    return key


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        r = httpx.get(
            f"{_base_url()}{path}",
            params={k: v for k, v in (params or {}).items() if v is not None},
            headers={"X-API-Key": _key()},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError:
        raise ApiProblemError("API unavailable", f"The HealthLake API at {_base_url()} does not answer.") from None
    if r.status_code == 200:
        data: dict[str, Any] = r.json()
        return data
    try:
        body = r.json()
    except ValueError:
        body = {}
    code = body.get("error_code", "")
    messages = {
        401: ("Access refused", "The dashboard API key is not accepted by the API."),
        403: ("Access refused", "The dashboard API key lacks a required scope."),
        410: ("Release purged", "This release was removed by the retention policy. Reload the page."),
        503: (
            "No data available",
            "No release has been published yet, or the database is unavailable."
            if code != "db_unavailable"
            else "The API cannot reach its database.",
        ),
    }
    title, detail = messages.get(r.status_code, ("Unexpected API answer", f"HTTP {r.status_code} {code}"))
    if code == "no_active_release":
        title, detail = "No published data yet", "Run the pipeline once; the dashboard shows only published releases."
    raise ApiProblemError(title, detail, r.status_code)


@st.cache_data(ttl=20, show_spinner=False)
def api_health() -> dict[str, Any]:
    try:
        r = httpx.get(f"{_base_url()}/health/ready", timeout=TIMEOUT)
        return {"reachable": True, "ready": r.status_code == 200, "status": r.status_code}
    except httpx.HTTPError:
        return {"reachable": False, "ready": False, "status": None}


@st.cache_data(ttl=20, show_spinner=False)
def current_release() -> dict[str, Any]:
    return _get("/v1/releases/current")


@st.cache_data(ttl=600, show_spinner=False)
def get(path: str, release_id: str | None, **params: Any) -> dict[str, Any]:
    """Cached call. The release id is part of the cache key, so a new publication never mixes with old data."""
    if release_id:
        params["release_id"] = release_id
    return _get(path, params)


@st.cache_data(ttl=600, show_spinner=False)
def get_all(path: str, release_id: str, max_rows: int = 5000, **params: Any) -> list[dict[str, Any]]:
    """Follow next_cursor; every page is read from the same pinned release."""
    rows: list[dict[str, Any]] = []
    cursor = None
    while True:
        q = {**params, "limit": 200, "release_id": release_id if cursor is None else None, "cursor": cursor}
        body = _get(path, q)
        if body["release_id"] != release_id and path != "/v1/pipeline-runs":
            raise ApiProblemError("Release changed", "The data changed release while loading. Reload the page.")
        rows += body["data"]
        cursor = body["page"]["next_cursor"]
        if not cursor or len(rows) >= max_rows:
            return rows


@dataclass(frozen=True)
class Pinned:
    release_id: str
    published_at: str | None
    short: str
