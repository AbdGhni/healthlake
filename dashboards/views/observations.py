from __future__ import annotations

import pandas as pd
import streamlit as st

from hl_dash import client, ui

pinned = ui.page_header("Observations", "Observation volumes per code, value type and unit.")
if pinned:
    top = st.slider("Codes shown", 5, 40, 20)
    try:
        rows = client.get_all("/v1/observations", pinned.release_id, max_rows=400, group_by="code")
        summary = client.get("/v1/summary", pinned.release_id)
    except client.ApiProblemError as p:
        ui.show_problem(p)
        st.stop()
    c = st.columns(3)
    ui.tile(c[0], "observations", summary["observations"])
    ui.tile(c[1], "components", summary["observation_components"])
    c[2].metric("Distinct (code, type, unit)", len(rows))
    if not rows:
        ui.empty_state("observations")
        st.stop()
    df = pd.DataFrame(rows)
    df["label"] = df["display"].fillna(df["code"]).str.slice(0, 50) + " [" + df["value_unit_code"].fillna("-") + "]"
    shown = df.head(top)
    st.altair_chart(
        ui.bar_h(
            shown,
            "observations",
            "label",
            "Observations",
            ["label", "code", "value_type", "value_unit_code", "observations", "distinct_patients"],
        ),
        use_container_width=True,
    )
    by_type = (
        df.groupby("value_type", as_index=False)["observations"].sum().sort_values("observations", ascending=False)
    )
    st.markdown("**Observations by value type**")
    st.dataframe(by_type, hide_index=True, use_container_width=False)
    with st.expander("Table view with statistics (per code and unit, never mixed)"):
        st.dataframe(
            df[
                [
                    "code",
                    "display",
                    "value_type",
                    "value_unit_code",
                    "observations",
                    "numeric_values",
                    "absent_values",
                    "distinct_patients",
                    "min_value",
                    "mean_value",
                    "max_value",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )
    ui.definitions(["obs_volume", "observations", "components"])
