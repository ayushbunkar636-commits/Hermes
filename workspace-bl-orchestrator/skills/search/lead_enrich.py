#!/usr/bin/env python3
"""lead_enrich.py — Shared liveness + excerpt enrichment for scan/discover paths."""
from __future__ import annotations

import os
import sys
import urllib.parse

_SEARCH_DIR = os.path.dirname(os.path.abspath(__file__))
if _SEARCH_DIR not in sys.path:
    sys.path.insert(0, _SEARCH_DIR)

from discover import BLOCKED_FETCH_DOMAINS  # noqa: E402
import read_tool  # noqa: E402
import advanced_crawler # noqa: E402

READ_MIN_WORDS = int(os.environ.get("BL_READ_MIN_WORDS", "20"))


def is_blocked_fetch_domain(url: str) -> bool:
    try:
        domain = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        return domain in BLOCKED_FETCH_DOMAINS or ("www." + domain) in BLOCKED_FETCH_DOMAINS
    except Exception:
        return False


def verify_and_enrich(
    url: str,
    title: str,
    snippet: str,
    *,
    min_words: int | None = None,
) -> tuple[bool, str, str, dict]:
    """Return (is_live, title, excerpt, seo_metrics). Snippet-trust for blocked domains."""
    title = (title or "").strip()
    snippet = (snippet or "").strip()
    mw = min_words if min_words is not None else READ_MIN_WORDS
    
    # Phase 3: Run the advanced crawler to extract real SEO metrics
    seo_metrics = advanced_crawler.crawl_url(url)

    if is_blocked_fetch_domain(url):
        if title or snippet:
            return True, title, snippet, seo_metrics
        return False, title, snippet, seo_metrics

    if title and len(snippet) >= 80:
        return True, title, snippet, seo_metrics

    rec = read_tool.read_url(url, out_dir=None, min_words=mw, write_file=False)
    if rec.get("ok"):
        new_title = rec.get("title_hint") or title
        new_excerpt = rec.get("excerpt_hint") or snippet
        return True, new_title, new_excerpt, seo_metrics

    if title or snippet:
        return True, title, snippet, seo_metrics
    return False, title, snippet, seo_metrics
