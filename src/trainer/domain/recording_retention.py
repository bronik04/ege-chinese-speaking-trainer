from __future__ import annotations

import calendar
from datetime import UTC, datetime

RETENTION_MONTHS = 6


def expires_at(created_at: int) -> int:
    created = datetime.fromtimestamp(created_at, UTC)
    month = created.month - 1 + RETENTION_MONTHS
    year, month = created.year + month // 12, month % 12 + 1
    day = min(created.day, calendar.monthrange(year, month)[1])
    return int(created.replace(year=year, month=month, day=day).timestamp())


def is_expired(expires_at: int, now: int) -> bool:
    return expires_at <= now
