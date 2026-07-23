#!/usr/bin/env python3
"""openweb_hunt.py — Open-web opportunity discovery (non site-scoped)."""
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
    clean_terms,
    parse_recency_hours,
    recency_score,
    extract_domain,
    url_key,
    DISCUSSION_TYPES,
    niche_overlap_score,
)
from lead_enrich import verify_and_enrich  # noqa: E402
from query_expander import expand_openweb_queries  # noqa: E402
from pipeline_log import plog_trace, plog_verbose, truncate  # noqa: E402

# Path patterns suggesting comment/discussion surfaces
_DISCUSSION_PATH_HINTS = (
    "/comments/", "/comment/", "/forum/", "/forums/", "/thread/", "/threads/",
    "/discussion/", "/discussions/", "/question/", "/questions/", "/ask/",
    "/topic/", "/topics/", "/post/", "/posts/", "/reply/", "/answers/",
    "/item?id=",  # HN
)

_SKIP_PATHS = (
    "/login", "/signin", "/signup", "/register", "/about", "/privacy",
    "/terms", "/contact", "/pricing", "/cart", "/checkout",
)


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
        return path not in ("", "/")
    except Exception:
        return False


def _looks_discussion_surface(url: str, title: str, snippet: str) -> bool:
    low_path = urllib.parse.urlparse(url).path.lower()
    if any(p in low_path for p in _SKIP_PATHS):
        return False
    if any(h in low_path for h in _DISCUSSION_PATH_HINTS):
        return True
    blob = f"{title} {snippet}".lower()
    hints = ("comment", "discussion", "forum", "thread", "question", "reply", "answered")
    return any(h in blob for h in hints)


def hunt_openweb(
    niche: str,
    *,
    keywords: list[str] | None = None,
    extra_queries: list[str] | None = None,
    max_results: int = 15,
    max_age_days: int = 7,
    skip_keys: set[str] | None = None,
) -> list[dict]:
    """Run open-web queries and return ranked lead dicts."""
    skip_keys = skip_keys or set()
    terms = clean_terms(niche, keywords)
    queries = expand_openweb_queries(niche, keywords, limit=10, extra=extra_queries)
    plog_verbose("openweb", "hunt_start", niche=truncate(niche, 80), queries=len(queries))
    raw: list[dict] = []
    seen: set[str] = set()

    for query in queries:
        if len(raw) >= max_results * 2:
            break
        plog_verbose("openweb", "search_query", query=truncate(query, 200))
        hits = search(query, max_results=max_results, mode="open")
        plog_verbose("openweb", "search_result", query=truncate(query, 200), raw=len(hits or []))
        for r in hits:
            url = (r.get("url") or "").strip()
            if not url or not _is_deep_url(url):
                continue
            key = url_key(url)
            if key in seen or key in skip_keys:
                plog_trace("openweb", "search_skip", url=truncate(url, 120), reason="duplicate")
                continue
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            if not _looks_discussion_surface(url, title, snippet):
                plog_trace("openweb", "search_skip", url=truncate(url, 120), reason="not_discussion")
                continue
            seen.add(key)
            hours = parse_recency_hours(f"{title} {snippet}")
            if max_age_days is not None and hours is not None and hours > max_age_days * 24:
                plog_trace("openweb", "search_skip", url=truncate(url, 120), reason="too_old")
                continue
            live, title, snippet, _ = verify_and_enrich(url, title, snippet)
            if not live:
                plog_trace("openweb", "search_skip", url=truncate(url, 120), reason="dead_link")
                continue
            rel = niche_overlap_score(title, snippet, terms)
            dom = extract_domain(url) or r.get("domain", "")
            plog_verbose("openweb", "search_hit", url=truncate(url, 120), domain=dom, title=truncate(title))
            raw.append({
                "url": url,
                "url_key": key,
                "submission_url": url,
                "domain": dom,
                "type": "forum",
                "target_title": title,
                "target_excerpt": snippet,
                "opportunity_context": "openweb",
                "opportunity_freshness": _freshness_str(hours),
                "posting_action": "reply",
                "platform": dom,
                "platform_weight": 0.65,
                "credibility_tier": 3,
                "relevance_score": rel,
                "recency_score": recency_score(hours),
            })

    raw.sort(key=lambda c: (c.get("relevance_score") or 0, c.get("recency_score", 0)), reverse=True)
    out = raw[:max_results]
    plog_verbose("openweb", "hunt_done", leads=len(out))
    return out
