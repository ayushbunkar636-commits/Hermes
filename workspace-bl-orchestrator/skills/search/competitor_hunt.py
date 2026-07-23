#!/usr/bin/env python3
"""competitor_hunt.py — Find opportunities on pages mentioning competitors."""
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
    niche_overlap_score,
)
from lead_enrich import verify_and_enrich  # noqa: E402
from query_expander import expand_competitor_queries  # noqa: E402
from x_filter import accept_x_url  # noqa: E402
from pipeline_log import plog_trace, plog_verbose, truncate  # noqa: E402

_SKIP_PATHS = (
    "/login", "/signin", "/signup", "/register", "/about", "/privacy",
    "/terms", "/contact", "/pricing", "/careers", "/jobs",
)


def _competitor_domains(competitors: list[str]) -> set[str]:
    out: set[str] = set()
    for c in competitors:
        c = c.strip().lower()
        if not c:
            continue
        if "." in c and " " not in c:
            out.add(c.lstrip("www."))
            if c.startswith("www."):
                out.add(c[4:])
        # brand-only names handled via URL check separately
    return out


def _is_competitor_own_page(url: str, competitors: list[str]) -> bool:
    dom = extract_domain(url)
    comp_doms = _competitor_domains(competitors)
    if dom in comp_doms:
        return True
    for c in competitors:
        brand = c.strip().lower().replace(" ", "")
        if brand and brand in dom.replace(".", "").replace("-", ""):
            if dom.endswith(c.strip().lower()) or brand in dom:
                return True
    return False


def _is_usable_surface(url: str, title: str, snippet: str) -> bool:
    if not accept_x_url(url):
        return False
    path = urllib.parse.urlparse(url).path.lower().rstrip("/")
    if path in ("", "/"):
        return False
    if any(p in path for p in _SKIP_PATHS):
        return False
    blob = f"{title} {snippet}".lower()
    # Need some sign of discussion or third-party mention context
    discussion_hints = (
        "comment", "discussion", "forum", "thread", "question", "review",
        "alternative", "vs", "compare", "reddit", "recommend",
    )
    return any(h in blob for h in discussion_hints) or "/comments/" in path or "/forum" in path


def _freshness_str(hours: float | None) -> str:
    if hours is None:
        return "unknown"
    if hours < 24:
        return f"~{max(1, int(hours))} hours ago"
    if hours < 168:
        return f"~{int(hours / 24)} days ago"
    return f"~{int(hours / 168)} weeks ago"


def hunt_competitors(
    niche: str,
    competitors: list[str],
    *,
    keywords: list[str] | None = None,
    extra_queries: list[str] | None = None,
    max_results: int = 12,
    max_age_days: int = 14,
    skip_keys: set[str] | None = None,
) -> list[dict]:
    """Search competitor mentions; keep only actionable third-party surfaces."""
    if not competitors:
        return []
    skip_keys = skip_keys or set()
    terms = clean_terms(niche, keywords)
    queries = expand_competitor_queries(competitors, niche, keywords, limit=10)
    if extra_queries:
        queries = list(dict.fromkeys(queries + extra_queries))[:12]
    plog_verbose(
        "competitor", "hunt_start",
        niche=truncate(niche, 80), competitors=",".join(competitors[:5]), queries=len(queries),
    )

    raw: list[dict] = []
    seen: set[str] = set()

    for query in queries:
        if len(raw) >= max_results * 2:
            break
        plog_verbose("competitor", "search_query", query=truncate(query, 200))
        hits = search(query, max_results=max_results, mode="open")
        plog_verbose("competitor", "search_result", query=truncate(query, 200), raw=len(hits or []))
        for r in hits:
            url = (r.get("url") or "").strip()
            if not url:
                continue
            if _is_competitor_own_page(url, competitors):
                plog_trace("competitor", "search_skip", url=truncate(url, 120), reason="competitor_own")
                continue
            key = url_key(url)
            if key in seen or key in skip_keys:
                plog_trace("competitor", "search_skip", url=truncate(url, 120), reason="duplicate")
                continue
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            if not _is_usable_surface(url, title, snippet):
                plog_trace("competitor", "search_skip", url=truncate(url, 120), reason="not_usable")
                continue
            seen.add(key)
            hours = parse_recency_hours(f"{title} {snippet}")
            if max_age_days is not None and hours is not None and hours > max_age_days * 24:
                plog_trace("competitor", "search_skip", url=truncate(url, 120), reason="too_old")
                continue
            live, title, snippet, _ = verify_and_enrich(url, title, snippet)
            if not live:
                plog_trace("competitor", "search_skip", url=truncate(url, 120), reason="dead_link")
                continue
            rel = niche_overlap_score(title, snippet, terms + [c for c in competitors if c])
            dom = extract_domain(url) or r.get("domain", "")
            plog_verbose("competitor", "search_hit", url=truncate(url, 120), domain=dom, title=truncate(title))
            raw.append({
                "url": url,
                "url_key": key,
                "submission_url": url,
                "domain": dom,
                "type": "comment",
                "target_title": title,
                "target_excerpt": snippet,
                "opportunity_context": "competitor_mention",
                "opportunity_freshness": _freshness_str(hours),
                "posting_action": "reply",
                "platform": dom,
                "platform_weight": 0.7,
                "credibility_tier": 3,
                "relevance_score": rel,
                "recency_score": recency_score(hours),
            })

    raw.sort(key=lambda c: (c.get("relevance_score") or 0, c.get("recency_score", 0)), reverse=True)
    out = raw[:max_results]
    plog_verbose("competitor", "hunt_done", leads=len(out))
    return out
