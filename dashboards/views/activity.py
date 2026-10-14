from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from hl_dash import client, ui

pinned = ui.page_header("Activity", "Encounters over time by category (UTC months).")
if pinned:
    f1, f2, f3 = st.columns([2, 2, 3])
    source = f1.selectbox("Source", ["All", *ui.SOURCE_COLORS], index=0)
    start = f2.date_input("From (inclusive)", value=date(2021, 1, 1))
    end = f3.date_input("To (exclusive)", value=date(2026, 1, 2))
    if end <= start:
        st.warning("The end date must be after the start date.")
        st.stop()
    try:
        rows = client.get_all(
            "/v1/encounters",
            pinned.release_id,
            group_by="day",
            source_id=None if source == "All" else source,
            start=start.isoformat(),
            end=end.isoformat(),
        )
    except client.ApiProblemError as p:
        ui.show_problem(p)
        st.stop()
    if not rows:
        ui.empty_state("encounters")
        st.stop()
    df = pd.DataFrame(rows)
    df["month"] = pd.to_datetime(df["activity_date"]).dt.to_period("M").dt.to_timestamp()
    monthly = df.groupby(["month", "encounter_category"], as_index=False)["encounters"].sum()
    present = [c for c in ui.CATEGORY_ORDER if c in set(monthly["encounter_category"])]
    colors = [ui.CATEGORY_COLORS[ui.CATEGORY_ORDER.index(c)] for c in present]
    total = int(monthly["encounters"].sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("Encounters in range", f"{total:,}".replace(",", " "))
    c2.metric(
        "Hospitalisations in range",
        f"{int(monthly.loc[monthly.encounter_category == 'inpatient', 'encounters'].sum()):,}".replace(",", " "),
    )
    c3.metric("Busiest month", monthly.groupby("month")["encounters"].sum().idxmax().strftime("%Y-%m"))
    chart = (
        alt.Chart(monthly)
        .mark_bar(stroke="#fcfcfb", strokeWidth=1)
        .encode(
            x=alt.X("yearmonth(month):T", title="Month (UTC)"),
            y=alt.Y("sum(encounters):Q", title="Encounters", stack="zero"),
            color=alt.Color(
                "encounter_category:N", title="Category", scale=alt.Scale(domain=present, range=colors), sort=present
            ),
            order=alt.Order("encounter_category:N"),
            tooltip=[
                alt.Tooltip("yearmonth(month):T", title="Month"),
                "encounter_category",
                alt.Tooltip("sum(encounters):Q", title="Encounters"),
            ],
        )
        .properties(height=340)
    )
    st.altair_chart(chart, use_container_width=True)
    with st.expander("Table view"):
        st.dataframe(
            monthly.pivot_table(
                index="month", columns="encounter_category", values="encounters", fill_value=0
            ).sort_index(ascending=False),
            use_container_width=True,
        )
    ui.definitions(["daily_activity", "encounters", "inpatient", "ambulatory"])
