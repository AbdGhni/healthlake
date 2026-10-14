"""Prometheus metrics computed from the control plane (low-cardinality labels only).

Labels are bounded: source_id (3), resource_type (7 projected + "other"), outcome (4), status (< 10),
check_id (catalog, < 50), severity (4). No batch, processing, attempt or patient id is ever a label.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from healthlake.validation.structural import PROJECTED

CACHE_SECONDS = 30.0


class PipelineCollector(Collector):
    def __init__(self, role: str = "api") -> None:
        self.role = role
        self._cache: tuple[float, list[Metric]] | None = None

    def collect(self) -> Iterator[Metric]:
        now = time.monotonic()
        if self._cache is None or now - self._cache[0] > CACHE_SECONDS:
            try:
                self._cache = (now, self._build())
            except Exception:  # noqa: BLE001 - metrics must not break the scrape; report it instead
                up = GaugeMetricFamily("healthlake_metrics_db_up", "1 if control metrics could be read")
                up.add_metric([], 0)
                yield up
                return
        yield from self._cache[1]

    def _build(self) -> list[Metric]:
        from healthlake.db import connect

        out: list[Metric] = []
        with connect(self.role) as conn:

            def gauge(name: str, doc: str, labels: list[str], rows: list[tuple[Any, ...]]) -> None:
                g = GaugeMetricFamily(name, doc, labels=labels)
                for *lv, value in rows:
                    g.add_metric([str(x) for x in lv], float(value or 0))
                out.append(g)

            up = GaugeMetricFamily("healthlake_metrics_db_up", "1 if control metrics could be read")
            up.add_metric([], 1)
            out.append(up)
            gauge(
                "healthlake_batches",
                "Registered batches by status",
                ["status"],
                conn.execute("SELECT status, count(*) FROM ctl.batch GROUP BY 1").fetchall(),
            )
            gauge(
                "healthlake_processings",
                "Processings by source and status",
                ["source_id", "status"],
                conn.execute(
                    "SELECT b.source_id, p.status, count(*) FROM ctl.processing p JOIN ctl.batch b"
                    " USING (batch_id) GROUP BY 1, 2"
                ).fetchall(),
            )
            gauge(
                "healthlake_attempts",
                "Attempts by status",
                ["status"],
                conn.execute("SELECT status, count(*) FROM ctl.attempt GROUP BY 1").fetchall(),
            )
            rows = conn.execute(
                "SELECT b.source_id, CASE WHEN o.resource_type = ANY(%s) THEN o.resource_type ELSE 'other' END,"
                " o.outcome, count(*) FROM bronze.resource_occurrence o JOIN ctl.processing p USING (processing_id)"
                " JOIN ctl.batch b ON b.batch_id=p.batch_id GROUP BY 1, 2, 3",
                (sorted(PROJECTED),),
            ).fetchall()
            gauge(
                "healthlake_resources",
                "Resource occurrences by source, type and outcome",
                ["source_id", "resource_type", "outcome"],
                rows,
            )
            gauge(
                "healthlake_quality_issues",
                "Quality issues by check and severity",
                ["check_id", "severity"],
                conn.execute("SELECT check_id, severity, count(*) FROM quality.issue GROUP BY 1, 2").fetchall(),
            )
            gauge(
                "healthlake_pipeline_last_duration_seconds",
                "Duration of the latest succeeded attempt per source (start to finish)",
                ["source_id"],
                conn.execute(
                    "SELECT DISTINCT ON (b.source_id) b.source_id,"
                    " extract(epoch from a.finished_at - a.started_at) FROM ctl.attempt a"
                    " JOIN ctl.processing p USING (processing_id) JOIN ctl.batch b ON b.batch_id=p.batch_id"
                    " WHERE a.status='succeeded' ORDER BY b.source_id, a.finished_at DESC"
                ).fetchall(),
            )
            gauge(
                "healthlake_last_success_timestamp_seconds",
                "Unix time of the latest succeeded attempt per source",
                ["source_id"],
                conn.execute(
                    "SELECT b.source_id, extract(epoch from max(a.finished_at)) FROM ctl.attempt a"
                    " JOIN ctl.processing p USING (processing_id) JOIN ctl.batch b ON b.batch_id=p.batch_id"
                    " WHERE a.status='succeeded' GROUP BY 1"
                ).fetchall(),
            )
            act = conn.execute(
                "SELECT extract(epoch from a.activated_at), extract(epoch from now() - a.activated_at)"
                " FROM ctl.active_release a WHERE a.release_id IS NOT NULL"
            ).fetchone()
            pub = GaugeMetricFamily(
                "healthlake_active_release_age_seconds", "Seconds since the active release was activated"
            )
            ts = GaugeMetricFamily("healthlake_active_release_activated_timestamp_seconds", "Activation time (unix)")
            if act:
                ts.add_metric([], float(act[0]))
                pub.add_metric([], float(act[1]))
            out += [pub, ts]
            gauge(
                "healthlake_releases",
                "Releases by status",
                ["status"],
                conn.execute("SELECT status, count(*) FROM ctl.release GROUP BY 1").fetchall(),
            )
        return out


def render_text(role: str = "api") -> str:
    from prometheus_client import CollectorRegistry, generate_latest

    reg = CollectorRegistry()
    reg.register(PipelineCollector(role))
    return generate_latest(reg).decode()
