# Screenshots

Real captures of the delivered dashboard and API docs, taken with `scripts/capture_screenshots.py`
(Playwright + Chromium) against a running API (uvicorn) and Streamlit.

| Capture | Data |
|---|---|
| current set (2026-10-15) | **demo** profile (100 Synthea patients requested per source, 328 exported) after the five demo scenarios (`scripts/demo.py --scenario all --runner local --profile demo`), active release `36d9ac94915b`; sandbox run without Docker |

The Data Quality page shows the quarantined row of the `quarantine` scenario (revision 2 of horizon-nord) and the
Pipeline Operations page shows the blocked batch, the injected crash and the refused release of the other
scenarios.
