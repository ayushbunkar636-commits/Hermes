#!/usr/bin/env python3
"""pipeline_tz.py — IST (Asia/Kolkata) timestamps for the backlink harvest pipeline."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("BL_TIMEZONE", "Asia/Kolkata"))
_SQLITE_FMT = "%Y-%m-%d %H:%M:%S"
_DISPLAY_FMT = "%d %b %Y, %-I:%M %p IST"


def now_sqlite() -> str:
    """IST timestamp for DB storage (compatible with stale comparisons)."""
    return datetime.now(TZ).strftime(_SQLITE_FMT)


def now_compact() -> str:
    """Compact IST timestamp for run/batch IDs."""
    return datetime.now(TZ).strftime("%Y%m%d-%H%M%S")


def hours_ago_sqlite(hours: float) -> str:
    """IST cutoff timestamp `hours` ago."""
    return (datetime.now(TZ) - timedelta(hours=hours)).strftime(_SQLITE_FMT)


def _parse_ts(ts: str) -> datetime | None:
    raw = (ts or "").strip()
    if not raw:
        return None
    if "T" in raw:
        try:
            normalized = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(TZ)
        except ValueError:
            return None
    try:
        dt = datetime.strptime(raw[:19], _SQLITE_FMT)
        return dt.replace(tzinfo=TZ)
    except ValueError:
        return None


def format_display(ts: str | None) -> str:
    """Human-readable IST string for cards/CLI."""
    if not ts or not str(ts).strip():
        return now_sqlite() + " IST"
    dt = _parse_ts(str(ts))
    if dt is None:
        return str(ts).strip()
    try:
        return dt.strftime(_DISPLAY_FMT)
    except ValueError:
        # Windows/WSL may not support %-I; fallback without zero-strip
        return dt.strftime("%d %b %Y, %I:%M %p IST").lstrip("0")


def format_sqlite_display(ts: str | None) -> str:
    """SQLite-style IST string with explicit suffix (list-pending, card_sent_at)."""
    if not ts or not str(ts).strip():
        return now_sqlite() + " IST"
    dt = _parse_ts(str(ts))
    if dt is None:
        cleaned = re.sub(r"\s*IST\s*$", "", str(ts).strip())
        return cleaned + " IST"
    return dt.strftime(_SQLITE_FMT) + " IST"


def format_utc_sqlite_display(ts: str | None) -> str | None:
    """Display SQLite UTC timezone('utc', now()) values in IST (whitelist scheduling)."""
    if not ts or not str(ts).strip():
        return None
    raw = str(ts).strip()
    try:
        dt = datetime.strptime(raw[:19], _SQLITE_FMT).replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ).strftime(_SQLITE_FMT) + " IST"
    except ValueError:
        return format_sqlite_display(raw)
