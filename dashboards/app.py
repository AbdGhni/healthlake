"""HealthLake dashboard (Streamlit). Reads the HealthLake API only; no database access.

Run: streamlit run dashboards/app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="HealthLake", page_icon="🩺", layout="wide")

pages = st.navigation(
    {
        "Analytics": [
            st.Page("views/overview.py", title="Overview", icon="🏠", default=True),
            st.Page("views/activity.py", title="Activity", icon="📅"),
            st.Page("views/diagnoses.py", title="Diagnoses", icon="🩺"),
            st.Page("views/observations.py", title="Observations", icon="🧪"),
        ],
        "Operations": [
            st.Page("views/quality.py", title="Data Quality", icon="✅"),
            st.Page("views/pipeline.py", title="Pipeline Operations", icon="⚙️"),
        ],
    }
)
st.sidebar.caption("Synthetic data only. Technical demonstration, not a certified healthcare platform.")
pages.run()
