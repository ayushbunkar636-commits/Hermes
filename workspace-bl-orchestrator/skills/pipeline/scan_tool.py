#!/usr/bin/env python3
"""scan_tool.py — Atomic, single-site opportunity scanner for the Farmer daemon.

The 24/7 nexus_daemon.py calls scan_single_url() for ONE whitelisted site per
tick. Uses search_tool (ddgs) via search.py, lead_enrich (Jina/snippet-trust),
and reddit_scan for reddit.com when subreddits are configured.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
_SEARCH_DIR = os.path.abspath(os.path.join(_PIPELINE_DIR, "..", "search"))
for _p in (_PIPELINE_DIR, _SEARCH_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from search import search  # noqa: E402
from discover import (  # noqa: E402
    parse_recency_hours,
    recency_score,
    extract_domain,
    url_key,
    DISCUSSION_TYPES,
    clean_terms,
    niche_overlap_score,
)
from lead_enrich import verify_and_enrich  # noqa: E402
from reddit_scan import scan_subreddits  # noqa: E402
from query_expander import expand_site_queries  # noqa: E402
from x_filter import accept_x_url  # noqa: E402
from pipeline_log import plog_trace, plog_verbose, truncate  # noqa: E402

SCAN_QUERY_LIMIT = int(os.environ.get("BL_SCAN_QUERY_LIMIT", "8"))

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_BLOCKED = "blocked"


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


def _log_skip(url: str, reason: str) -> None:
    plog_trace("scan", "search_skip", url=truncate(url, 120), reason=reason)


def _parse_search_results(
    result: dict,
    domain: str,
    *,
    max_results: int,
    max_age_days: int | None,
    platform_weight: float,
    credibility_tier: int,
    opp_type: str,
    skip_keys: set[str],
    seen: set[str],
    terms: list[str] | None = None,
) -> list[dict]:
    out: list[dict] = []
    for r in result.get("results", []):
        url = (r.get("url") or "").strip()
        if not url or not _is_deep_url(url):
            if url:
                _log_skip(url, "shallow_url")
            continue
        if not accept_x_url(url):
            _log_skip(url, "x_filter")
            continue
        key = url_key(url)
        if key in seen or key in skip_keys:
            _log_skip(url, "duplicate")
            continue
        url_dom = extract_domain(url)
        if domain not in url_dom and url_dom not in domain:
            _log_skip(url, "domain_mismatch")
            continue
        seen.add(key)
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        hours = parse_recency_hours(f"{title} {snippet}")
        if max_age_days is not None and hours is not None and hours > max_age_days * 24:
            _log_skip(url, "too_old")
            continue
        live, title, snippet, seo_metrics = verify_and_enrich(url, title, snippet)
        if not live:
            _log_skip(url, "dead_link")
            continue
            
        # Phase 9: Advanced Duplicate & Canonical Detection
        canonical_url = seo_metrics.get("canonical_url")
        if seo_metrics.get("has_canonical") and canonical_url:
            canonical_key = url_key(canonical_url)
            if canonical_key in seen or canonical_key in skip_keys:
                _log_skip(url, "duplicate_canonical")
                continue
            seen.add(canonical_key)
            url = canonical_url
            key = canonical_key
            
        rel = niche_overlap_score(title, snippet, terms) if terms else None
        plog_verbose(
            "scan", "search_hit",
            url=truncate(url, 120),
            title=truncate(title),
            relevance=rel,
        )
        out.append({
            "url": url,
            "url_key": key,
            "submission_url": url,
            "domain": extract_domain(url) or domain,
            "type": opp_type,
            "target_title": title,
            "target_excerpt": snippet,
            "opportunity_context": "",
            "opportunity_freshness": _freshness_str(hours),
            "posting_action": "reply" if opp_type in DISCUSSION_TYPES else "submit",
            "platform": domain,
            "platform_weight": platform_weight,
            "credibility_tier": credibility_tier,
            "relevance_score": rel,
            "recency_score": recency_score(hours),
            "page_language": seo_metrics.get("page_language"),
            "has_canonical": seo_metrics.get("has_canonical", False),
            "is_dofollow": seo_metrics.get("is_dofollow", True),
            "is_ugc": seo_metrics.get("is_ugc", False),
            "is_sponsored": seo_metrics.get("is_sponsored", False),
            "outbound_link_count": seo_metrics.get("outbound_link_count", 0),
            "raw_html": seo_metrics.get("full_html", ""),
        })
    return out


def scan_single_url(
    domain: str,
    niche: str,
    *,
    max_results: int = 5,
    platform_weight: float = 0.6,
    credibility_tier: int = 3,
    opp_type: str = "forum",
    max_age_days: int | None = 7,
    check_liveness: bool = True,
    cache_path: str | None = None,
    skip_keys: set[str] | None = None,
    subreddits: list[str] | None = None,
    keywords: list[str] | None = None,
    extra_queries: list[str] | None = None,
) -> tuple[str, list[dict]]:
    domain = domain.lower().strip().lstrip("www.")
    skip_keys = skip_keys or set()

    from harvester_registry import get_harvester  # noqa: E402

    adapter_name, adapter_fn = get_harvester(domain, {})
    kwargs = {
        "keywords": keywords,
        "extra_queries": extra_queries,
        "max_results": max_results,
        "max_age_days": max_age_days,
        "skip_keys": skip_keys,
        "cursor": {},
        "stats": {},
        "cache_path": cache_path,
        "subreddits": subreddits,
        "platform_weight": platform_weight,
        "credibility_tier": credibility_tier,
    }
    status, leads, _, _ = adapter_fn(domain, niche, **kwargs)
    plog_verbose("scan", "scan_done", domain=domain, status=status, leads=len(leads), adapter=adapter_name)
    return status, leads


    parser = argparse.ArgumentParser(description="Atomic single-site opportunity scan")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--niche", required=True)
    parser.add_argument("--max", type=int, default=5, dest="max_results")
    parser.add_argument("--max-age-days", type=int, default=7, dest="max_age_days")
    parser.add_argument("--no-liveness", action="store_true", dest="no_liveness")
    parser.add_argument("--cache", dest="cache_path", default=None)
    parser.add_argument("--out", dest="out", default=None)
    args = parser.parse_args()

    status, leads = scan_single_url(
        args.domain,
        args.niche,
        max_results=args.max_results,
        max_age_days=args.max_age_days,
        check_liveness=not args.no_liveness,
        cache_path=args.cache_path,
    )

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"status": status, "domain": args.domain, "leads": leads}, f, indent=2, ensure_ascii=False)

    print(f"SCAN_ONE: status={status} domain={args.domain} leads={len(leads)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
