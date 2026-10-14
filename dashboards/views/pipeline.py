from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from hl_dash import client, ui

pinned = ui.page_header("Pipeline Operations", "Ingestion attempts and releases.")
if pinned:
    try:
        runs = client.get_all("/v1/pipeline-runs", pinned.release_id, max_rows=200)
        releases = client.get("/v1/releases", None, limit=20)
    except client.ApiProblemError as p:
        ui.show_problem(p)
        st.stop()
    df = pd.DataFrame(runs)
    c = st.columns(4)
    if df.empty:
        ui.empty_state("pipeline runs")
        st.stop()
    c[0].metric("Attempts", len(df))
    c[1].metric("Succeeded", int((df.status == "succeeded").sum()))
    c[2].metric("Blocked or failed", int(df.status.isin(["blocked", "failed"]).sum()))
    last_ok = df.loc[df.status == "succeeded", "finished_at"].max() if (df.status == "succeeded").any() else None
    c[3].metric("Last success", ui.age(last_ok) + " ago" if last_ok else "-")
    df["Status"] = df["status"].map(ui.status_label)
    df["error_code"] = df["error_code"].fillna("")
    ok = df[df.status == "succeeded"].copy()
    if not ok.empty:
        ok["run"] = (
            ok["source_id"].str.replace("horizon-", "")
            + " r"
            + ok["source_revision"].astype(str)
            + " "
            + ok["started_at"].str[5:16].str.replace("T", " ")
        )
        st.markdown("**Duration of succeeded attempts (start to Silver load)**")
        st.altair_chart(
            alt.Chart(ok)
            .mark_bar(cornerRadiusEnd=4, size=14)
            .encode(
                x=alt.X("duration_seconds:Q", title="Seconds"),
                y=alt.Y("run:N", title=None, sort=None, axis=alt.Axis(labelOverlap=False, labelLimit=260)),
                color=alt.Color(
                    "source_id:N",
                    title="Source",
                    scale=alt.Scale(domain=list(ui.SOURCE_COLORS), range=list(ui.SOURCE_COLORS.values())),
                ),
                tooltip=["source_id", "source_revision", "duration_seconds", "received", "accepted"],
            )
            .properties(height=max(140, 36 * len(ok))),
            use_container_width=True,
        )
    st.markdown("**Attempts**")
    st.dataframe(
        df[
            [
                "Status",
                "source_id",
                "source_revision",
                "current_step",
                "error_code",
                "started_at",
                "duration_seconds",
                "received",
                "accepted",
                "rejected",
                "orchestrator_run_id",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.markdown("**Releases**")
    rel = pd.DataFrame(releases["data"])
    rel["Status"] = rel["status"].map(ui.status_label)
    rel["Active"] = rel["active"].map({True: "● active", False: ""})
    rel["release"] = rel["release_id"].str[:12]
    st.dataframe(
        rel[["release", "Status", "Active", "published_at", "created_at"]], hide_index=True, use_container_width=True
    )
    ui.definitions(["pipeline_runs", "freshness"])
