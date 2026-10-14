"""Shared layout: notice, pinned release header, tiles, definitions, palette-based Altair charts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from hl_dash import client
from hl_dash.indicators import INDICATORS, help_text

NOTICE = (
    "HealthLake is a technical demonstration using synthetic data only. It is not a certified healthcare "
    "platform and is not intended or authorized to process real personal health data."
)

# Reference categorical palette (validated order, light surface). Color follows the entity, never its rank.
SOURCE_COLORS = {"horizon-central": "#2a78d6", "horizon-nord": "#eb6834", "horizon-sud": "#1baf7a"}
CATEGORY_ORDER = ["ambulatory", "inpatient", "emergency", "observation", "virtual", "home_health", "other"]
CATEGORY_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
SERIES_1 = "#2a78d6"
STATUS = {
    "pass": ("✅", "Pass"),
    "warn": ("⚠️", "Warning"),
    "fail": ("⛔", "Failed"),
    "skipped": ("◻️", "Skipped"),
    "succeeded": ("✅", "Succeeded"),
    "failed": ("⛔", "Failed"),
    "blocked": ("⛔", "Blocked"),
    "running": ("⏳", "Running"),
    "published": ("✅", "Published"),
    "gate_failed": ("⛔", "Gate failed"),
    "purged": ("🗑️", "Purged"),
    "built": ("◻️", "Built"),
    "building": ("⏳", "Building"),
}


def status_label(s: str) -> str:
    icon, label = STATUS.get(s, ("•", s))
    return f"{icon} {label}"


def page_header(title: str, subtitle: str) -> client.Pinned | None:
    """Render the common header and pin the release for every card of this page run."""
    st.title(title)
    st.caption(subtitle)
    st.info(NOTICE, icon=":material/info:")
    health = client.api_health()
    try:
        rel = client.current_release()
    except client.ApiProblemError as p:
        show_problem(p, health)
        return None
    pinned = client.Pinned(rel["release_id"], rel.get("published_at"), rel["release_id"][:12])
    cols = st.columns([2, 3, 2])
    cols[0].markdown(
        f"**Release** `{pinned.short}`",
        help=f"Full id: {pinned.release_id}. Every card of this page "
        "reads this release, even if another one is published while you look at it.",
    )
    cols[1].markdown(
        f"**Published** {fmt_dt(pinned.published_at)} ({age(pinned.published_at)} ago)", help=help_text("freshness")
    )
    api_state = "🟢 API ready" if health["ready"] else ("🟠 API not ready" if health["reachable"] else "🔴 API down")
    cols[2].markdown(f"**{api_state}**")
    st.divider()
    return pinned


def show_problem(p: client.ApiProblemError, health: dict[str, Any] | None = None) -> None:
    if p.title.startswith("No published"):
        st.warning(f"**{p.title}.** {p.detail}", icon="🕓")
    else:
        st.error(f"**{p.title}.** {p.detail}", icon="⚠️")
    if health and not health["reachable"]:
        st.caption("Operators: see docs/runbooks/api-unavailable.md.")


def fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def age(value: str | None) -> str:
    if not value:
        return "-"
    secs = (datetime.now(UTC) - datetime.fromisoformat(value)).total_seconds()
    if secs < 3600:
        return f"{int(secs // 60)} min"
    if secs < 86400:
        return f"{secs / 3600:.1f} h"
    return f"{secs / 86400:.1f} days"


def tile(col: Any, key: str, value: Any) -> None:
    text = f"{value:,}".replace(",", " ") if isinstance(value, int) else str(value)
    col.metric(INDICATORS[key]["label"], text, help=help_text(key))


def definitions(keys: list[str]) -> None:
    with st.expander("Indicator definitions (definition, formula, source, grain, period, limits)"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Indicator": INDICATORS[k]["label"],
                        **{
                            c.title(): INDICATORS[k][c]
                            for c in ("definition", "formula", "source", "grain", "period", "limits")
                        },
                    }
                    for k in keys
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )


def bar_h(
    df: pd.DataFrame,
    value: str,
    label: str,
    value_title: str,
    tooltip: list[Any],
    color: str = SERIES_1,
    height: int | None = None,
) -> alt.Chart:
    """Horizontal bars, one series = one color, sorted by value, thin bars with rounded ends."""
    return (
        alt.Chart(df)
        .mark_bar(color=color, cornerRadiusEnd=4, size=14)
        .encode(
            x=alt.X(f"{value}:Q", title=value_title, axis=alt.Axis(grid=True, gridOpacity=0.3)),
            y=alt.Y(f"{label}:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320, labelOverlap=False)),
            tooltip=tooltip,
        )
        .properties(height=height or max(120, 26 * len(df)))
    )


def empty_state(what: str) -> None:
    st.caption(f"No {what} in this release for the selected filters.")
