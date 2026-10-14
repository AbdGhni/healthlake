"""Dashboard pages render from real recorded API responses, and degrade to readable messages.

These are component tests: HTTP answers are recorded responses of the real API (tests/fixtures/api_responses).
The live end-to-end check (real API + real Streamlit + browser) is scripts/capture_screenshots.py.
Run with the dashboard venv: .venvs/dashboard/bin/python -m pytest tests/dashboard
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # app/dev venv without streamlit
    pytest.skip("streamlit not installed in this environment", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "dashboards"
FIX = ROOT / "tests" / "fixtures" / "api_responses"
sys.path.insert(0, str(DASH))

ROUTES = {
    "/v1/releases/current": "releases_current",
    "/v1/summary": "summary",
    "/v1/diagnoses": "diagnoses",
    "/v1/quality": "quality",
    "/v1/pipeline-runs": "pipeline_runs",
    "/v1/releases": "releases",
}


def fake_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    if path == "/v1/encounters" and params.get("group_by") == "day":
        name = "encounters_day"
    elif path == "/v1/observations" and params.get("group_by") == "code":
        name = "observations_code"
    else:
        name = ROUTES[path]
    data: dict[str, Any] = json.loads((FIX / f"{name}.json").read_text())
    return data


@pytest.fixture(autouse=True)
def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    from hl_dash import client

    client.current_release.clear()
    client.get.clear()
    client.get_all.clear()
    client.api_health.clear()
    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(client, "api_health", lambda: {"reachable": True, "ready": True, "status": 200})


@pytest.mark.parametrize("page", ["overview", "activity", "diagnoses", "observations", "quality", "pipeline"])
def test_page_renders_real_payloads(page: str) -> None:
    at = AppTest.from_file(str(DASH / "views" / f"{page}.py"), default_timeout=30).run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown) + " ".join(i.value for i in at.info)
    assert "synthetic data only" in text
    assert "c87706efd0af" in text  # the pinned release is shown


def test_overview_numbers_come_from_the_api() -> None:
    at = AppTest.from_file(str(DASH / "views" / "overview.py"), default_timeout=30).run()
    summary = json.loads((FIX / "summary.json").read_text())
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Synthetic patients"] == str(summary["patients"])
    assert metrics["Hospitalisations"] == str(summary["encounters_by_category"]["inpatient"])


def test_no_published_release_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from hl_dash import client

    def no_release(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise client.ApiProblemError("No published data yet", "Run the pipeline once.", 503)

    monkeypatch.setattr(client, "_get", no_release)
    at = AppTest.from_file(str(DASH / "views" / "overview.py"), default_timeout=30).run()
    assert not at.exception
    assert any("No published data yet" in w.value for w in at.warning)
    assert not at.metric  # nothing invented


def test_api_down_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from hl_dash import client

    monkeypatch.setenv("HEALTHLAKE_API_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("HEALTHLAKE_DASHBOARD_API_KEY", "irrelevant")
    import importlib

    importlib.reload(client)
    at = AppTest.from_file(str(DASH / "views" / "diagnoses.py"), default_timeout=30).run()
    assert not at.exception
    assert any("API unavailable" in e.value for e in at.error)
    assert not at.metric


def test_dashboard_has_no_database_access() -> None:
    for p in DASH.rglob("*.py"):
        src = p.read_text()
        for forbidden in ("psycopg", "sqlalchemy", "healthlake.db", "HEALTHLAKE_DB_"):
            assert forbidden not in src, f"{p} references {forbidden}"
