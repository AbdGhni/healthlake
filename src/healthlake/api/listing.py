"""Keyset pagination over a release schema with deterministic ordering.

Each listing declares its FROM clause, selected columns, an ordering key made of SQL expressions (all ascending,
descending keys are expressed as negated values) and the SQL type of each key part. A page selects rows whose key
tuple is strictly greater than the cursor's key tuple, ordered by the key: no offset, no skipped or repeated rows
as long as the release does not change - and the release is pinned in the cursor.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from healthlake.api import db


@dataclass(frozen=True)
class Listing:
    name: str
    from_sql: str  # may contain {schema}
    columns: list[str]
    key_exprs: list[str]
    key_types: list[str]


def filters_hash(filters: dict[str, Any]) -> str:
    clean = {
        k: (v.isoformat() if isinstance(v, datetime | date) else str(v) if v is not None else None)
        for k, v in sorted(filters.items())
    }
    return hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()[:32]


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Decimal):
        return str(v)
    return v


def run_page(
    listing: Listing, schema: str, where: list[str], params: dict[str, Any], limit: int, after: list[Any] | None
) -> tuple[list[dict[str, Any]], list[Any] | None]:
    key = ", ".join(listing.key_exprs)
    conds = list(where)
    p = dict(params)
    if after is not None:
        if len(after) != len(listing.key_exprs):
            raise ValueError("cursor key does not match listing")
        placeholders = []
        for i, (val, typ) in enumerate(zip(after, listing.key_types, strict=True)):
            p[f"k{i}"] = val
            placeholders.append(f"CAST(:k{i} AS {typ})")
        conds.append(f"({key}) > ({', '.join(placeholders)})")
    sql = (
        f"SELECT {', '.join(listing.columns)}, {', '.join(f'{e} AS _k{i}' for i, e in enumerate(listing.key_exprs))}"
        f" FROM {listing.from_sql.format(schema=db.quote_schema(schema))}"
        f"{' WHERE ' + ' AND '.join(conds) if conds else ''}"
        f" ORDER BY {key} LIMIT :limit_plus_one"
    )
    p["limit_plus_one"] = limit + 1
    rows = db.fetch_all(sql, p)
    more = len(rows) > limit
    rows = rows[:limit]
    next_key = [_jsonable(rows[-1][f"_k{i}"]) for i in range(len(listing.key_exprs))] if more and rows else None
    data = [{k: _jsonable(v) for k, v in r.items() if not k.startswith("_k")} for r in rows]
    return data, next_key
