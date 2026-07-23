#!/usr/bin/env python3
"""pipeline_log.py — Structured logging for the backlink harvest pipeline."""
from __future__ import annotations

import os
import re
import sys
from typing import Any

from pipeline_tz import now_sqlite

_LEVELS = {"off": 0, "info": 1, "verbose": 2, "trace": 3}
_LOG_SNIPPET = int(os.environ.get("BL_LOG_SNIPPET", "160"))


def _current_level() -> int:
    raw = (os.environ.get("BL_LOG_LEVEL") or "info").strip().lower()
    return _LEVELS.get(raw, 1)


def truncate(s: Any, n: int | None = None) -> str:
    """Truncate text for log lines."""
    if s is None:
        return ""
    text = re.sub(r"\s+", " ", str(s)).strip()
    limit = n if n is not None else _LOG_SNIPPET
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _format_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return f"{v:.2f}"
    text = str(v)
    if " " in text or "=" in text or '"' in text:
        return f'"{text.replace(chr(34), chr(39))}"'
    return text


def format_fields(**fields: Any) -> str:
    parts = []
    for k, v in fields.items():
        if v is None or v == "":
            continue
        parts.append(f"{k}={_format_value(v)}")
    return (" " + " ".join(parts)) if parts else ""


def plog(stage: str, level: str, msg: str, **fields: Any) -> None:
    """Emit a log line if BL_LOG_LEVEL allows it."""
    need = _LEVELS.get(level, 1)
    if _current_level() < need:
        return
    ts = now_sqlite()
    extra = format_fields(**fields)
    print(f"[nexus {ts}] [{stage}|{level}] {msg}{extra}", flush=True)


def plog_info(stage: str, msg: str, **fields: Any) -> None:
    plog(stage, "info", msg, **fields)


def plog_verbose(stage: str, msg: str, **fields: Any) -> None:
    plog(stage, "verbose", msg, **fields)


def plog_trace(stage: str, msg: str, **fields: Any) -> None:
    plog(stage, "trace", msg, **fields)


def level_enabled(level: str) -> bool:
    return _current_level() >= _LEVELS.get(level, 1)


def reset_level_for_tests(level: str) -> None:
    """Test helper — set BL_LOG_LEVEL in-process."""
    os.environ["BL_LOG_LEVEL"] = level
