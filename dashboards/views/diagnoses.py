from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from hl_dash import client, ui

pinned = ui.page_header("Diagnoses", "Most frequent diagnosis codes and the patients concerned.")
if pinned:
    f1, f2 = st.columns([2, 2])
    system = f1.selectbox("Code system", ["All", "SNOMED CT", "LOINC", "RxNorm", "other", "no system"])
    top = f2.slider("Codes shown", 5, 40, 15)
    try:
        rows = client.get_all(
            "/v1/diagnoses", pinned.release_id, max_rows=top, system_label=None if system == "All" else system
        )
    except client.ApiProblemError as p:
        ui.show_problem(p)
        st.stop()
    if not rows:
        ui.empty_state("diagnoses")
        st.stop()
    df = pd.DataFrame(rows[:top])
    df["label"] = df["display"].fillna(df["code"]).str.slice(0, 60) + " (" + df["code"] + ")"
    left, right = st.columns(2)
    left.markdown("**Conditions recorded**")
    left.altair_chart(
        ui.bar_h(df, "conditions", "label", "Conditions", ["label", "system_label", "conditions", "distinct_patients"]),
        use_container_width=True,
    )
    right.markdown("**Distinct patients**")
    right.altair_chart(
        ui.bar_h(
            df, "distinct_patients", "label", "Patients", ["label", "system_label", "conditions", "distinct_patients"]
        ),
        use_container_width=True,
    )
    st.caption("Patients are not additive across codes: one patient usually has several diagnoses.")
    with st.expander("Table view"):
        st.dataframe(
            df[
                [
                    "system_label",
                    "code",
                    "display",
                    "conditions",
                    "distinct_patients",
                    "first_onset_at",
                    "last_onset_at",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )
    ui.definitions(["conditions", "patients_per_dx", "diagnosis_codes"])
    _ = alt
