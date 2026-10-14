# Dashboard

> HealthLake is a technical demonstration using synthetic data only.
> It is not a certified healthcare platform and is not intended or
> authorized to process real personal health data.

Streamlit app in `dashboards/` (entry `dashboards/app.py`). It calls the HealthLake API only (key with scopes
`read` + `ops`, file `HEALTHLAKE_DASHBOARD_API_KEY_FILE`); it contains no database driver (tested).

| Page | Content | API |
|---|---|---|
| Overview | patients, encounters, outpatient visits, hospitalisations, diagnoses, distinct codes, observations, components, prescriptions, event period, by-source chart and table | /v1/summary |
| Activity | encounters per UTC month stacked by category, date and source filters, table view | /v1/encounters?group_by=day |
| Diagnoses | top codes by conditions and by distinct patients, code-system filter, table view | /v1/diagnoses |
| Observations | volume per (code, unit), value-type breakdown, statistics per code and unit | /v1/observations?group_by=code |
| Data Quality | received/rejected, terminology coverage, clinical-data age, release checks with status icon + label, per-processing reconciliation, quarantine counts | /v1/quality |
| Pipeline Operations | attempts with status, durations, last success, releases with active marker | /v1/pipeline-runs, /v1/releases |

Behaviour:
- Each page run pins one `release_id` (from `/v1/releases/current`) and passes it to every call, so all cards of
  a page show the same release. Cached calls are keyed by endpoint, filters and release id.
- Header on every page: synthetic-data notice, release id, publication time and age, API state.
- States: "No published data yet" (no release), "API unavailable", access refused, purged release; no number is
  shown when the API cannot provide it.
- Every indicator has a definition, formula, source, grain, period and limits (`dashboards/hl_dash/indicators.py`),
  shown as a tooltip on the tile and in the "Indicator definitions" table of each page.
- Colours: reference categorical palette in fixed order (source and encounter category keep their colour whatever
  the filter), one colour for single-series bars, status shown with icon + label, table view next to charts.

Tests: `tests/dashboard` (Streamlit AppTest on recorded responses of the real API: 6 pages, numbers match the API,
no-release and API-down states, no database access). Real end-to-end captures: `scripts/capture_screenshots.py`,
images in `docs/screenshots/`.
