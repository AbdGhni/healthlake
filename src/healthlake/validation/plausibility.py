"""Extreme-value flags (warnings). A value is compared only to a range with the same code and unit;
no unit conversion is attempted here."""

from __future__ import annotations

from functools import cache
from typing import Any

from healthlake.adapters.base import Issue
from healthlake.generation.synthea import load_json


@cache
def ranges() -> dict[tuple[str, str], tuple[float, float, str]]:
    data = load_json("plausibility.json")
    return {(r["code"], r["unit"]): (float(r["min"]), float(r["max"]), r["label"]) for r in data["ranges"]}


def _code(cc: Any) -> str | None:
    if isinstance(cc, dict):
        for c in cc.get("coding") or []:
            if isinstance(c, dict) and c.get("system") == "http://loinc.org" and c.get("code"):
                return str(c["code"])
    return None


def check_observation(res: dict[str, Any], loc: str, file_sha: str | None) -> list[Issue]:
    out: list[Issue] = []
    elements = [("value", res)] + [
        (f"component[{i}]", c) for i, c in enumerate(res.get("component") or []) if isinstance(c, dict)
    ]
    for where, el in elements:
        q = el.get("valueQuantity")
        code = _code(el.get("code"))
        if not isinstance(q, dict) or code is None:
            continue
        v, unit = q.get("value"), q.get("code") or q.get("unit")
        r = ranges().get((code, str(unit)))
        if r is None or isinstance(v, bool) or not isinstance(v, int | float):
            continue
        lo, hi, label = r
        if not lo <= v <= hi:
            out.append(
                Issue(
                    "value.extreme",
                    "warning",
                    "value_out_of_plausible_range",
                    f"{where}: {label} {v} {unit} outside [{lo}, {hi}]",
                    loc,
                    file_sha,
                )
            )
    return out
