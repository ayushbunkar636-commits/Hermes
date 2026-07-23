#!/usr/bin/env python3
"""query_planner.py — Combinatorial query rotation + epsilon-greedy bandit selection."""
from __future__ import annotations

import os
import random
import sys

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
_SEARCH_DIR = os.path.abspath(os.path.join(_PIPELINE_DIR, "..", "search"))
for _p in (_PIPELINE_DIR, _SEARCH_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from discover import clean_terms  # noqa: E402
from query_expander import build_site_template_pool  # noqa: E402

QUERY_BATCH_SIZE = int(os.environ.get("BL_SCAN_QUERY_LIMIT", "8"))
EXPLORE_RATIO = float(os.environ.get("BL_QUERY_EXPLORE_RATIO", "0.2"))


def _keyword_pool(niche: str, keywords: list[str] | None, vocab: list[str] | None) -> list[str]:
    base = clean_terms(niche, keywords)
    extra = [t for t in (vocab or []) if t and t not in base]
    merged = base + extra
    return merged if merged else ([niche.strip()] if niche.strip() else ["discussion"])


def _template_yield(stats: dict[str, dict], template_id: str) -> float:
    row = stats.get(template_id) or {}
    runs = int(row.get("runs") or 0)
    new_leads = int(row.get("new_leads") or 0)
    if runs == 0:
        return 0.5  # optimistic prior for unexplored
    return new_leads / runs


def plan_site_queries(
    domain: str,
    niche: str,
    keywords: list[str] | None,
    *,
    vocab: list[str] | None = None,
    extra: list[str] | None = None,
    cursor: dict | None = None,
    stats: dict[str, dict] | None = None,
    batch_size: int | None = None,
) -> tuple[list[tuple[str, str]], dict]:
    """Pick next query batch using cursor rotation + epsilon-greedy bandit.

    Returns ([(template_id, query), ...], updated_cursor).
    """
    batch_size = batch_size or QUERY_BATCH_SIZE
    cursor = dict(cursor or {})
    stats = stats or {}
    terms = _keyword_pool(niche, keywords, vocab)
    pool = build_site_template_pool(domain, terms, extra=extra)
    if not pool:
        return [], cursor

    pool_offset = int(cursor.get("pool_offset") or 0) % len(pool)
    rotated = pool[pool_offset:] + pool[:pool_offset]

    # Epsilon-greedy: explore random slice or exploit high-yield templates
    if random.random() < EXPLORE_RATIO:
        candidates = rotated[: batch_size * 3]
        random.shuffle(candidates)
        picked = candidates[:batch_size]
    else:
        scored = sorted(
            rotated,
            key=lambda item: _template_yield(stats, item[0]),
            reverse=True,
        )
        picked = scored[:batch_size]

    new_offset = (pool_offset + batch_size) % len(pool)
    new_cursor = {**cursor, "pool_offset": new_offset, "terms_count": len(terms)}
    return picked, new_cursor
