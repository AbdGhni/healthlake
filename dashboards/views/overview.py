from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from hl_dash import client, ui

pinned = ui.page_header("Overview", "Réseau Hospitalier Horizon (fictional) - three synthetic sources, one release.")
if pinned:
    try:
        s = client.get("/v1/summary", pinned.release_id)
    except client.ApiProblemError as p:
        ui.show_problem(p)
        st.stop()
    cats = s["encounters_by_category"]
    r1 = st.columns(4)
    ui.tile(r1[0], "patients", s["patients"])
    ui.tile(r1[1], "encounters", s["encounters"])
    ui.tile(r1[2], "ambulatory", cats.get("ambulatory", 0))
    ui.tile(r1[3], "inpatient", cats.get("inpatient", 0))
    r2 = st.columns(5)
    ui.tile(r2[0], "conditions", s["conditions"])
    ui.tile(r2[1], "diagnosis_codes", s["distinct_diagnosis_codes"])
    ui.tile(r2[2], "observations", s["observations"])
    ui.tile(r2[3], "components", s["observation_components"])
    ui.tile(r2[4], "prescriptions", s["medication_requests"])
    st.caption(f"Clinical events from {ui.fmt_dt(s['first_encounter_at'])} to {ui.fmt_dt(s['last_encounter_at'])}.")

    st.subheader("By source")
    df = pd.DataFrame(s["by_source"])
    if df.empty:
        ui.empty_state("source")
    else:
        left, right = st.columns([3, 2])
        chart = (
            alt.Chart(df)
            .mark_bar(cornerRadiusEnd=4, size=18)
            .encode(
                x=alt.X("encounters:Q", title="Encounters"),
                y=alt.Y("source_id:N", title=None),
                color=alt.Color(
                    "source_id:N",
                    title="Source",
                    scale=alt.Scale(domain=list(ui.SOURCE_COLORS), range=list(ui.SOURCE_COLORS.values())),
                ),
                tooltip=["source_id", "patients", "encounters"],
            )
            .properties(height=150)
        )
        left.altair_chart(chart, use_container_width=True)
        right.dataframe(
            df.rename(columns={"source_id": "Source", "patients": "Patients", "encounters": "Encounters"}),
            hide_index=True,
            use_container_width=True,
        )
    ui.definitions(
        [
            "patients",
            "encounters",
            "ambulatory",
            "inpatient",
            "conditions",
            "diagnosis_codes",
            "observations",
            "components",
            "prescriptions",
            "freshness",
        ]
    )
