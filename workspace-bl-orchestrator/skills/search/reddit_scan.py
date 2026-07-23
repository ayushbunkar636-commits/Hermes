#!/usr/bin/env python3
"""reddit_scan.py — Subreddit-aware Reddit discovery using search_tool + lead_enrich."""
from __future__ import annotations

import os
import sys
import urllib.parse

_SEARCH_DIR = os.path.dirname(os.path.abspath(__file__))
_PIPELINE_DIR = os.path.abspath(os.path.join(_SEARCH_DIR, "..", "pipeline"))
for _p in (_SEARCH_DIR, _PIPELINE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from search_tool import search  # noqa: E402
from discover import (  # noqa: E402
    parse_recency_hours,
    recency_score,
    extract_domain,
    url_key,
    DISCUSSION_TYPES,
    clean_terms,
    niche_overlap_score,
)
from query_expander import expand_reddit_queries  # noqa: E402
from lead_enrich import verify_and_enrich  # noqa: E402
from pipeline_log import plog_trace, plog_verbose, truncate  # noqa: E402


def _freshness_str(hours: float | None) -> str:
    if hours is None:
        return "unknown"
    if hours < 2:
        return "~1 hour ago"
    if hours < 24:
        return f"~{int(hours)} hours ago"
    if hours < 168:
        return f"~{int(hours / 24)} days ago"
    if hours < 720:
        return f"~{int(hours / 168)} weeks ago"
    return f"~{int(hours / 720)} months ago"


def _is_deep_url(url: str) -> bool:
    try:
        path = urllib.parse.urlparse(url).path.rstrip("/")
        return path not in ("", "/") and "/comments/" in path.lower()
    except Exception:
        return False


def _build_queries(
    niche: str,
    subreddits: list[str],
    keywords: list[str],
    extra_queries: list[str] | None = None,
) -> list[str]:
    return expand_reddit_queries(
        niche, keywords, subreddits, limit=14, extra=extra_queries,
    )


def scan_subreddits(
    niche: str,
    *,
    subreddits: list[str] | None = None,
    keywords: list[str] | None = None,
    max_results: int = 15,
    max_age_days: int = 7,
    platform_weight: float = 0.95,
    credibility_tier: int = 1,
    skip_keys: set[str] | None = None,
    extra_queries: list[str] | None = None,
) -> tuple[str, list[dict]]:
    """Scan Reddit via subreddit-targeted queries. Returns (status, leads)."""
    skip_keys = skip_keys or set()
    terms = clean_terms(niche, keywords or [])
    queries = _build_queries(niche, subreddits or [], keywords or [], extra_queries)
    for q in queries:
        plog_verbose("scan", "scan_queries", query=truncate(q, 200))
    raw: list[dict] = []
    seen: set[str] = set()
    blocked = False
    got_any = False

    for query in queries:
        if len(raw) >= max_results * 2:
            break
        results = search(query, max_results=max_results, mode="site")
        raw_count = len(results) if results else 0
        plog_verbose(
            "scan", "search_query",
            query=truncate(query, 200), status="ok" if results else "empty", raw=raw_count,
        )
        if not results:
            continue
        got_any = True
        for r in results:
            url = (r.get("url") or "").strip()
            if not url or not _is_deep_url(url):
                if url:
                    plog_trace("scan", "search_skip", url=truncate(url, 120), reason="shallow_url")
                continue
            dom = extract_domain(url) or "reddit.com"
            if "reddit.com" not in dom:
                plog_trace("scan", "search_skip", url=truncate(url, 120), reason="not_reddit")
                continue
            key = url_key(url)
            if key in seen or key in skip_keys:
                plog_trace("scan", "search_skip", url=truncate(url, 120), reason="duplicate")
                continue
            seen.add(key)
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            hours = parse_recency_hours(f"{title} {snippet}")
            if max_age_days is not None and hours is not None and hours > max_age_days * 24:
                plog_trace("scan", "search_skip", url=truncate(url, 120), reason="too_old")
                continue
            live, title, snippet, _ = verify_and_enrich(url, title, snippet)
            if not live:
                plog_trace("scan", "search_skip", url=truncate(url, 120), reason="dead_link")
                continue
            rel = niche_overlap_score(title, snippet, terms) if terms else None
            plog_verbose(
                "scan", "search_hit",
                url=truncate(url, 120), title=truncate(title), relevance=rel,
            )
            raw.append({
                "url": url,
                "url_key": key,
                "submission_url": url,
                "domain": dom,
                "type": "qa_community",
                "target_title": title,
                "target_excerpt": snippet,
                "opportunity_context": "",
                "opportunity_freshness": _freshness_str(hours),
                "posting_action": "reply",
                "platform": "reddit.com",
                "platform_weight": platform_weight,
                "credibility_tier": credibility_tier,
                "relevance_score": rel,
                "recency_score": recency_score(hours),
            })

    if not raw:
        status = "blocked" if blocked and not got_any else "empty"
        return status, []

    raw.sort(key=lambda c: c.get("recency_score", 0), reverse=True)
    return "ok", raw[:max_results]
