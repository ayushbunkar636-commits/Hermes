#!/usr/bin/env python3
"""generic_search.py — DDG tiered search via query_planner (fallback for any domain)."""
from __future__ import annotations

import os
import sys
import time
import urllib.parse

_PIPELINE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "pipeline"))
_SEARCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_PIPELINE_DIR, _SEARCH_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from search import search  # noqa: E402
from discover import clean_terms, url_key, extract_domain  # noqa: E402
from query_planner import plan_site_queries  # noqa: E402
from lead_enrich import verify_and_enrich  # noqa: E402
from x_filter import accept_x_url  # noqa: E402
from pipeline_log import plog_verbose, plog_trace, truncate  # noqa: E402
from harvesters._common import make_lead  # noqa: E402

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_BLOCKED = "blocked"

QUERY_DELAY = float(os.environ.get("BL_SEARCH_QUERY_DELAY", "4"))


def _is_deep_url(url: str) -> bool:
    try:
        path = urllib.parse.urlparse(url).path.rstrip("/")
        return path not in ("", "/")
    except Exception:
        return False


def _parse_hits(
    result: dict,
    domain: str,
    *,
    max_results: int,
    max_age_days: int | None,
    skip_keys: set[str],
    seen: set[str],
    terms: list[str],
    platform_weight: float,
    credibility_tier: int,
) -> list[dict]:
    out: list[dict] = []
    for r in result.get("results", []):
        url = (r.get("url") or "").strip()
        if not url or not _is_deep_url(url):
            if url:
                plog_trace("scan", "search_skip", url=truncate(url, 120), reason="shallow_url")
            continue
        if not accept_x_url(url):
            plog_trace("scan", "search_skip", url=truncate(url, 120), reason="x_filter")
            continue
        key = url_key(url)
        if key in seen or key in skip_keys:
            plog_trace("scan", "search_skip", url=truncate(url, 120), reason="duplicate")
            continue
        url_dom = extract_domain(url)
        if domain not in url_dom and url_dom not in domain:
            plog_trace("scan", "search_skip", url=truncate(url, 120), reason="domain_mismatch")
            continue
        seen.add(key)
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        hours_raw = f"{title} {snippet}"
        from discover import parse_recency_hours  # noqa: E402
        hours = parse_recency_hours(hours_raw)
        if max_age_days is not None and hours is not None and hours > max_age_days * 24:
            plog_trace("scan", "search_skip", url=truncate(url, 120), reason="too_old")
            continue
        live, title, snippet, _ = verify_and_enrich(url, title, snippet)
        if not live:
            plog_trace("scan", "search_skip", url=truncate(url, 120), reason="dead_link")
            continue
        lead = make_lead(
            url=url, domain=domain, title=title, snippet=snippet,
            platform=domain, platform_weight=platform_weight,
            credibility_tier=credibility_tier, terms=terms,
        )
        if lead is None:
            plog_trace("scan", "search_skip", url=truncate(url, 120), reason="non_english")
            continue
        plog_verbose(
            "scan", "search_hit",
            url=truncate(url, 120), title=truncate(title), relevance=lead.get("relevance_score"),
        )
        out.append(lead)
    return out


def harvest(
    domain: str,
    niche: str,
    *,
    keywords: list[str] | None = None,
    vocab: list[str] | None = None,
    extra_queries: list[str] | None = None,
    max_results: int = 20,
    max_age_days: int | None = 14,
    cache_path: str | None = None,
    skip_keys: set[str] | None = None,
    cursor: dict | None = None,
    stats: dict | None = None,
    platform_weight: float = 0.6,
    credibility_tier: int = 3,
    **kwargs,
) -> tuple[str, list[dict], dict, dict[str, int]]:
    """Returns (status, leads, new_cursor, template_stats)."""
    skip_keys = skip_keys or set()
    terms = clean_terms(niche, keywords)
    batch, new_cursor = plan_site_queries(
        domain, niche, keywords,
        vocab=vocab, extra=extra_queries,
        cursor=cursor, stats=stats,
    )
    plog_verbose(
        "scan", "scan_start",
        domain=domain, niche=truncate(niche, 80),
        terms=",".join(terms[:8]) or None, max_results=max_results, queries=len(batch),
    )
    for tid, q in batch:
        plog_verbose("scan", "scan_queries", query=truncate(q, 200), template_id=tid)

    raw: list[dict] = []
    seen: set[str] = set()
    queries_run = 0
    queries_ok = 0
    template_stats: dict[str, int] = {tid: 0 for tid, _ in batch}

    for template_id, query in batch:
        if len(raw) >= max_results:
            break
        before = len(raw)
        queries_run += 1
        try:
            result = search(
                query, max_results=max_results + 3,
                cache_path=cache_path, raise_on_failure=False,
            )
        except Exception as exc:
            plog_verbose("scan", "search_query", query=truncate(query, 200), status="exception", error=str(exc)[:120])
            if QUERY_DELAY > 0:
                time.sleep(QUERY_DELAY)
            continue
        status = result.get("status")
        raw_count = len(result.get("results") or [])
        if status == "ok":
            queries_ok += 1
        plog_verbose("scan", "search_query", query=truncate(query, 200), status=status, raw=raw_count)
        if result.get("results"):
            raw.extend(_parse_hits(
                result, domain, max_results=max_results, max_age_days=max_age_days,
                skip_keys=skip_keys, seen=seen, terms=terms,
                platform_weight=platform_weight, credibility_tier=credibility_tier,
            ))
        template_stats[template_id] = max(0, len(raw) - before)
        if QUERY_DELAY > 0:
            time.sleep(QUERY_DELAY)
        if len(raw) >= max_results:
            break

    if not raw:
        all_queries_failed = queries_run > 0 and queries_ok == 0
        final = STATUS_BLOCKED if all_queries_failed else STATUS_EMPTY
        plog_verbose("scan", "scan_done", domain=domain, status=final, leads=0)
        return final, [], new_cursor, template_stats

    raw.sort(key=lambda c: c.get("recency_score", 0), reverse=True)
    leads = raw[:max_results]
    plog_verbose("scan", "scan_done", domain=domain, status=STATUS_OK, leads=len(leads))
    return STATUS_OK, leads, new_cursor, template_stats
