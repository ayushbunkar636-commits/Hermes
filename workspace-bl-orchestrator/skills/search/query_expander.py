#!/usr/bin/env python3
"""query_expander.py — Varied search query templates for backlink discovery."""
from __future__ import annotations

from discover import clean_terms  # noqa: E402


def _dedupe(queries: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        key = q.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(q.strip())
        if len(out) >= limit:
            break
    return out


def expand_site_queries(
    domain: str,
    niche: str = "",
    keywords: list[str] | None = None,
    *,
    limit: int = 8,
    extra: list[str] | None = None,
) -> list[str]:
    """Site-scoped queries for whitelist domain scans."""
    terms = clean_terms(niche, keywords)
    if not terms:
        terms = [niche.strip()] if niche.strip() else ["discussion"]
    dom = domain.lower().strip().lstrip("www.")
    queries: list[str] = []
    for term in terms[:4]:
        queries.append(f"site:{dom} {term}")
        queries.append(f"site:{dom} {term} discussion")
        queries.append(f"site:{dom} {term} question")
        queries.append(f'site:{dom} "{term}" recommendations')
    if extra:
        queries.extend(extra)
    return _dedupe(queries, limit)


def expand_reddit_queries(
    niche: str = "",
    keywords: list[str] | None = None,
    subreddits: list[str] | None = None,
    *,
    limit: int = 12,
    extra: list[str] | None = None,
) -> list[str]:
    """Subreddit-targeted or broad Reddit queries."""
    terms = clean_terms(niche, keywords)
    if not terms:
        terms = [niche.strip()] if niche.strip() else ["discussion"]
    queries: list[str] = []
    subs = [s.strip().lstrip("r/").lstrip("/") for s in (subreddits or []) if s.strip()]
    if subs:
        for sub in subs[:8]:
            for term in terms[:3]:
                queries.append(f"site:reddit.com/r/{sub} {term}")
                queries.append(f"site:reddit.com/r/{sub} {term} question")
                queries.append(f"site:reddit.com/r/{sub} {term} help")
    else:
        for term in terms[:4]:
            queries.append(f"site:reddit.com {term}")
            queries.append(f"site:reddit.com {term} discussion")
            queries.append(f"site:reddit.com {term} question")
    if extra:
        queries.extend(extra)
    return _dedupe(queries, limit)


def expand_openweb_queries(
    niche: str = "",
    keywords: list[str] | None = None,
    *,
    limit: int = 10,
    extra: list[str] | None = None,
) -> list[str]:
    """Non site-scoped queries for open-web hunting."""
    terms = clean_terms(niche, keywords)
    if not terms:
        terms = [niche.strip()] if niche.strip() else ["forum"]
    queries: list[str] = []
    for term in terms[:4]:
        queries.append(f"{term} forum discussion")
        queries.append(f"{term} community question")
        queries.append(f'best {term} recommendations')
        queries.append(f"{term} review comparison")
        queries.append(f"{term} vs alternative")
    if extra:
        queries.extend(extra)
    return _dedupe(queries, limit)


def expand_competitor_queries(
    competitors: list[str],
    niche: str = "",
    keywords: list[str] | None = None,
    *,
    limit: int = 10,
) -> list[str]:
    """Queries seeded from competitor names/brands."""
    comps = [c.strip() for c in competitors if c and c.strip()]
    terms = clean_terms(niche, keywords)
    if not comps:
        return []
    queries: list[str] = []
    for comp in comps[:5]:
        queries.append(f'"{comp}" {terms[0] if terms else niche} discussion')
        queries.append(f'"{comp}" alternative forum')
        queries.append(f'"{comp}" vs review')
        if terms:
            queries.append(f'"{comp}" {terms[0]} question')
    return _dedupe(queries, limit)


# Combinatorial flywheel templates (keyword x modifier rotation)
_SITE_MODIFIERS = (
    "",
    "discussion",
    "question",
    "help",
    "recommendations",
    "how to",
    "best",
    "vs",
    "alternative",
    "looking for",
)


def build_site_template_pool(
    domain: str,
    terms: list[str],
    *,
    extra: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Return (template_id, query_string) pairs for site-scoped combinatorial search."""
    dom = domain.lower().strip().lstrip("www.")
    pool: list[tuple[str, str]] = []
    if not terms:
        terms = ["discussion"]
    for term in terms:
        for mod in _SITE_MODIFIERS:
            tid = f"site|{term}|{mod or 'plain'}"
            if mod:
                q = f"site:{dom} {term} {mod}"
            else:
                q = f"site:{dom} {term}"
            pool.append((tid, q))
    if extra:
        for i, q in enumerate(extra):
            pool.append((f"extra|{i}", q))
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for tid, q in pool:
        key = q.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((tid, q))
    return out
