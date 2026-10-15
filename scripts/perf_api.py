"""API latency under concurrent clients (real HTTP against a running API).

  python scripts/perf_api.py --api http://127.0.0.1:8000 --key <analyst/dashboard key> --clients 5 --rounds 40

Each client loops over the endpoint mix in its own order; latency is measured per request (wall clock, client
side, including HTTP). Reports p50/p95/p99 per endpoint and overall, throughput and errors.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import threading
import time
from pathlib import Path
from typing import Any

import httpx

AGGREGATES = [
    "/v1/summary",
    "/v1/diagnoses?limit=50",
    "/v1/observations?group_by=code&limit=50",
    "/v1/encounters?group_by=day&limit=200",
    "/v1/quality",
]
LISTS = [
    "/v1/patients?limit=50",
    "/v1/encounters?limit=50&source_id=horizon-nord",
    "/v1/observations?limit=50&code=8867-4",
    "/v1/medication-requests?limit=50",
]


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, max(0, round(p / 100 * len(s)) - 1))] * 1000, 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--clients", type=int, default=5)
    ap.add_argument("--rounds", type=int, default=40)
    ap.add_argument("--label", default="api")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    paths = AGGREGATES + LISTS
    results: dict[str, list[float]] = {p: [] for p in paths}
    errors: list[str] = []
    lock = threading.Lock()

    def client(seed: int) -> None:
        rng = random.Random(seed)  # noqa: S311 - request order shuffling, not security
        with httpx.Client(base_url=a.api, headers={"X-API-Key": a.key}, timeout=30) as c:
            for _ in range(a.rounds):
                order = paths[:]
                rng.shuffle(order)
                for p in order:
                    t0 = time.perf_counter()
                    try:
                        r = c.get(p)
                    except httpx.HTTPError as exc:
                        with lock:
                            errors.append(f"{p} {type(exc).__name__}")
                        continue
                    dt = time.perf_counter() - t0
                    with lock:
                        if r.status_code == 200:
                            results[p].append(dt)
                        else:
                            errors.append(f"{p} {r.status_code}")

    t0 = time.perf_counter()
    threads = [threading.Thread(target=client, args=(i,)) for i in range(a.clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.perf_counter() - t0
    agg = [x for p in AGGREGATES for x in results[p]]
    lst = [x for p in LISTS for x in results[p]]
    report: dict[str, Any] = {
        "label": a.label,
        "clients": a.clients,
        "rounds": a.rounds,
        "requests": len(agg) + len(lst),
        "errors": len(errors),
        "error_samples": errors[:5],
        "duration_s": round(total, 1),
        "throughput_rps": round((len(agg) + len(lst)) / total, 1),
        "aggregates_ms": {
            "p50": pct(agg, 50),
            "p95": pct(agg, 95),
            "p99": pct(agg, 99),
            "mean": round(statistics.mean(agg) * 1000, 1) if agg else None,
        },
        "lists_ms": {
            "p50": pct(lst, 50),
            "p95": pct(lst, 95),
            "p99": pct(lst, 99),
            "mean": round(statistics.mean(lst) * 1000, 1) if lst else None,
        },
        "per_endpoint_ms": {p: {"n": len(v), "p50": pct(v, 50), "p95": pct(v, 95)} for p, v in results.items() if v},
    }
    print(json.dumps(report, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
