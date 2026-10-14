"""FHIR R4 primitive parsing that keeps original text and precision. No date is invented:
partial dates keep their precision and get no instant."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
DATE_RE = re.compile(r"^(\d{4})(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")
DATETIME_RE = re.compile(
    r"^(\d{4})(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01])"
    r"(T([01]\d|2[0-3]):[0-5]\d:([0-5]\d|60)(\.\d{1,9})?(Z|[+-]((0\d|1[0-3]):[0-5]\d|14:00)))?)?)?$"
)


@dataclass(frozen=True)
class ParsedTime:
    raw: str
    precision: str  # year | month | day | second
    instant: datetime | None  # UTC, only when precision == second
    day: date | None  # only when precision == day


def parse_date(raw: str) -> ParsedTime | None:
    m = DATE_RE.match(raw)
    if not m:
        return None
    if m.group(4):
        try:
            d = date.fromisoformat(raw)
        except ValueError:
            return None
        return ParsedTime(raw, "day", None, d)
    return ParsedTime(raw, "month" if m.group(2) else "year", None, None)


def parse_datetime(raw: str) -> ParsedTime | None:
    if not DATETIME_RE.match(raw):
        return None
    if "T" not in raw:
        return parse_date(raw)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return ParsedTime(raw, "second", dt.astimezone(UTC), None)
