#!/usr/bin/env python3
"""harvester_registry.py — Route whitelist domains to the best harvest adapter."""
from __future__ import annotations

import os
import sys
from typing import Any, Callable

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
_SEARCH_DIR = os.path.abspath(os.path.join(_PIPELINE_DIR, "..", "search"))
for _p in (_PIPELINE_DIR, _SEARCH_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import whitelist_db as wdb  # noqa: E402
from harvesters.generic_search import harvest as generic_harvest, STATUS_OK, STATUS_EMPTY, STATUS_BLOCKED  # noqa: E402
from harvesters.reddit_api import harvest as reddit_harvest  # noqa: E402
from harvesters.hn_algolia import harvest as hn_harvest  # noqa: E402
from harvesters.rss_sitemap import harvest as rss_harvest  # noqa: E402

SEARCH_CACHE = os.environ.get("BL_SEARCH_CACHE", "/tmp/backlink-daemon-search-cache.json")


def _reddit_host(domain: str) -> str:
    """Host part only — reddit.com/r/foo -> reddit.com."""
    d = domain.lower().strip().lstrip("www.")
    return d.split("/", 1)[0]


def _is_reddit(domain: str) -> bool:
    host = _reddit_host(domain)
    return host in ("reddit.com", "www.reddit.com") or host.endswith(".reddit.com")


def _subreddit_from_domain(domain: str) -> str | None:
    """Extract subreddit from whitelist domain like reddit.com/r/CryptoMarkets."""
    d = domain.lower().strip().lstrip("www.")
    marker = "/r/"
    if marker not in d:
        return None
    sub = d.split(marker, 1)[1].split("/")[0].strip()
    return sub or None


def _is_hn(domain: str) -> bool:
    d = domain.lower().strip().lstrip("www.")
    return d in ("news.ycombinator.com", "ycombinator.com")


def _pick_adapter(domain: str, cursor: dict) -> tuple[str, Callable[..., tuple[str, list[dict], dict, dict[str, int]]]]:
    if _is_reddit(domain):
        return "reddit_api", reddit_harvest
    if _is_hn(domain):
        return "hn_algolia", hn_harvest
    if cursor.get("feed_url"):
        return "rss_sitemap", rss_harvest
    # Try RSS once if cursor has rss_tried flag not set - handled inside rss with probe
    return "generic_search", generic_harvest


def harvest_site(
    site: dict,
    *,
    niche: str,
    cfg: dict,
    db_path: str,
    max_results: int = 20,
    max_age_days: int = 14,
    extra_queries: list[str] | None = None,
) -> tuple[str, list[dict], dict, dict[str, int], str]:
    """Harvest one whitelist site. Returns (status, leads, cursor, template_stats, adapter_name)."""
    site_id = site["id"]
    project_id = site["project_id"]
    domain = site["domain"]

    cursor = wdb.get_harvest_cursor(site_id, db_path=db_path)
    stats = wdb.get_query_stats(project_id, domain, db_path=db_path)
    skip_keys = wdb.get_existing_url_keys(project_id, db_path=db_path)
    vocab = wdb.get_vocab_terms(project_id, db_path=db_path)
    keywords = cfg.get("target_keywords") or []
    subreddits = cfg.get("subreddits") or []

    adapter_name, adapter_fn = _pick_adapter(domain, cursor)

    subreddit_list = subreddits if isinstance(subreddits, list) else []
    parsed_sub = _subreddit_from_domain(domain)
    if adapter_name == "reddit_api" and parsed_sub:
        subreddit_list = [parsed_sub]

    kwargs: dict[str, Any] = {
        "keywords": keywords if isinstance(keywords, list) else [],
        "vocab": vocab,
        "extra_queries": extra_queries,
        "max_results": max_results,
        "max_age_days": max_age_days,
        "skip_keys": skip_keys,
        "cursor": cursor,
        "stats": stats,
        "cache_path": SEARCH_CACHE,
        "subreddits": subreddit_list,
    }

    status, leads, new_cursor, template_stats = adapter_fn(domain, niche, **kwargs)

    # If generic returned empty and no feed tried, attempt RSS probe once
    if adapter_name == "generic_search" and status == STATUS_EMPTY and not cursor.get("rss_tried"):
        new_cursor = {**new_cursor, "rss_tried": True}
        rss_status, rss_leads, rss_cursor, rss_stats = rss_harvest(domain, niche, **kwargs)
        if rss_leads:
            return rss_status, rss_leads, rss_cursor, rss_stats, "rss_sitemap"

    new_cursor = {**new_cursor, "adapter": adapter_name}
    return status, leads, new_cursor, template_stats, adapter_name


def get_harvester(domain: str, cursor: dict | None = None) -> tuple[str, Callable[..., tuple[str, list[dict], dict, dict[str, int]]]]:
    """Public registry lookup for tests and scan_tool."""
    return _pick_adapter(domain, cursor or {})


__all__ = ["harvest_site", "get_harvester", "STATUS_OK", "STATUS_EMPTY", "STATUS_BLOCKED"]
