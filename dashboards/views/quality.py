from __future__ import annotations

import pandas as pd
import streamlit as st

from hl_dash import client, ui

pinned = ui.page_header("Data Quality", "Reconciliation, quarantine and release checks of the pinned release.")
if pinned:
    try:
        q = client.get("/v1/quality", pinned.release_id)
    except client.ApiProblemError as p:
        ui.show_problem(p)
        st.stop()
    checks = {c["check_id"]: c for c in q["release_checks"]}
    procs = pd.DataFrame(q["processings"])
    c = st.columns(4)
    received = int(procs["received"].sum()) if not procs.empty else 0
    rejected = int(procs["rejected"].sum()) if not procs.empty else 0
    c[0].metric("Resources received", f"{received:,}".replace(",", " "))
    c[1].metric("Rejected (quarantine)", f"{rejected:,}".replace(",", " "))
    term = checks.get("release.terminology_coverage")
    c[2].metric(
        ui.INDICATORS["terminology"]["label"],
        f"{term['observed'] * 100:.1f} %" if term and term["observed"] is not None else "-",
        help=ui.help_text("terminology"),
    )
    fresh = checks.get("release.freshness_clinical_data")
    c[3].metric(
        ui.INDICATORS["event_age"]["label"],
        f"{fresh['observed']:.0f} days" if fresh and fresh["observed"] is not None else "-",
        help=ui.help_text("event_age"),
    )
    st.subheader("Release checks")
    pct_checks = {
        "release.terminology_coverage",
        "release.completeness_encounter_end",
        "release.completeness_observation_effective",
    }

    def fmt(check: str, value: float | None) -> str:
        if value is None:
            return "-"
        if check in pct_checks:
            return f"{value * 100:.1f} %"
        return f"{value:g}"

    rc = pd.DataFrame(
        [
            {
                "Check": k,
                "Status": ui.status_label(v["status"]),
                "Observed": fmt(k, v["observed"]),
                "Threshold": fmt(k, v["threshold"]),
            }
            for k, v in sorted(checks.items())
        ]
    )

    st.dataframe(rc, hide_index=True, use_container_width=True)
    st.caption(
        f"Quality catalogue {q['catalog_version']}. Thresholds are a demonstration policy, not medical "
        "thresholds. Terminology coverage checks code system URIs only; codes are not validated against a "
        "terminology server."
    )
    st.subheader("Processings in this release")
    if procs.empty:
        ui.empty_state("processings")
    else:
        procs["reject_rate_new_pct"] = (procs["reject_rate_new"].fillna(0) * 100).round(3)
        procs["reconciles"] = (
            procs["received"] == procs["accepted"] + procs["deduplicated"] + procs["rejected"] + procs["out_of_scope"]
        ).map({True: "✅ yes", False: "⛔ no"})
        st.dataframe(
            procs[
                [
                    "source_id",
                    "source_revision",
                    "received",
                    "accepted",
                    "deduplicated",
                    "rejected",
                    "out_of_scope",
                    "reconciles",
                    "reject_rate_new_pct",
                    "fatal_issues",
                    "error_issues",
                    "warning_issues",
                ]
            ].rename(columns={"reject_rate_new_pct": "reject rate new (%)"}),
            hide_index=True,
            use_container_width=True,
        )
        st.caption("Reconciliation: received = accepted + deduplicated + rejected + out of scope.")
    st.subheader("Quarantine issues by check")
    issues = pd.DataFrame(q["issues"])
    if issues.empty:
        st.success("No quarantine issue for the processings of this release.", icon="✅")
    else:
        st.dataframe(issues, hide_index=True, use_container_width=True)
    ui.definitions(["reject_rate", "terminology", "event_age"])
