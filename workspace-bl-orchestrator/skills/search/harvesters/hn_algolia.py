#!/usr/bin/env python3
"""hn_algolia.py — Hacker News harvester via Algolia API (date-sorted, paginated)."""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

_SEARCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PIPELINE_DIR = os.path.abspath(os.path.join(_SEARCH_DIR, "..", "pipeline"))
for _p in (_SEARCH_DIR, _PIPELINE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from discover import clean_terms, url_key  # noqa: E402
from pipeline_log import plog_verbose, truncate  # noqa: E402
from harvesters._common import make_lead  # noqa: E402

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_BLOCKED = "blocked"

HN_ITEM = "https://news.ycombinator.com/item?id={id}"


def _fetch_hn(query: str, page: int) -> dict | None:
    params = urllib.parse.urlencode({"query": query, "page": page})
    url = f"https://hn.algolia.com/api/v1/search_by_date?{params}"
    plog_verbose("scan", "hn_algolia_fetch", query=truncate(query, 80), page=page)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        plog_verbose("scan", "hn_fetch_error", error=str(exc)[:120])
        return None


def harvest(
    domain: str,
    niche: str,
    *,
    keywords: list[str] | None = None,
    max_results: int = 20,
    skip_keys: set[str] | None = None,
    cursor: dict | None = None,
    vocab: list[str] | None = None,
    **kwargs,
) -> tuple[str, list[dict], dict, dict[str, int]]:
    skip_keys = skip_keys or set()
    cursor = dict(cursor or {})
    terms = clean_terms(niche, keywords)
    if vocab:
        for v in vocab:
            if v not in terms:
                terms.append(v)
    if not terms:
        terms = [niche.strip() or "discussion"]

    term_idx = int(cursor.get("term_index") or 0) % len(terms)
    page = int(cursor.get("page") or 0)
    term = terms[term_idx]
    tid = f"hn|{term}|p{page}"

    data = _fetch_hn(term, page)
    hits = (data or {}).get("hits") or []
    leads: list[dict] = []
    for hit in hits:
        oid = hit.get("objectID") or hit.get("story_id")
        if not oid:
            continue
        url = HN_ITEM.format(id=oid)
        key = url_key(url)
        if key in skip_keys:
            continue
        title = hit.get("title") or hit.get("story_title") or ""
        snippet = hit.get("comment_text") or hit.get("story_text") or title
        lead = make_lead(
            url=url, domain="news.ycombinator.com", title=title, snippet=str(snippet)[:400],
            platform="news.ycombinator.com", platform_weight=0.9, credibility_tier=1,
            opp_type="forum", context="hn_algolia", terms=terms,
        )
        if lead is None:
            continue
        leads.append(lead)
        if len(leads) >= max_results:
            break

    nb_pages = int((data or {}).get("nbPages") or 0)
    if page + 1 < nb_pages and page + 1 < 10:
        new_cursor = {"term_index": term_idx, "page": page + 1}
    else:
        new_cursor = {"term_index": (term_idx + 1) % len(terms), "page": 0}

    stats = {tid: len(leads)}
    if not leads:
        return STATUS_EMPTY if data else STATUS_BLOCKED, [], new_cursor, stats
    return STATUS_OK, leads, new_cursor, stats
