#!/usr/bin/env python3
"""reddit_api.py — Paginated Reddit JSON harvester (new + search)."""
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

UA = os.environ.get("BL_REDDIT_UA", "backlink-farmer/1.0 (by /u/openclaw)")
PER_PAGE = int(os.environ.get("BL_REDDIT_PAGE_SIZE", "25"))


def _fetch_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        plog_verbose("scan", "reddit_fetch_error", url=truncate(url, 120), error=str(exc)[:120])
        return None


def _posts_from_listing(data: dict | None) -> tuple[list[dict], str | None]:
    if not data or not isinstance(data, dict):
        return [], None
    children = (data.get("data") or {}).get("children") or []
    after = (data.get("data") or {}).get("after")
    posts = []
    for ch in children:
        d = (ch or {}).get("data") or {}
        url = (d.get("url") or "").strip()
        permalink = d.get("permalink") or ""
        if permalink and not permalink.startswith("http"):
            url = f"https://www.reddit.com{permalink}"
        if not url or "/comments/" not in url.lower():
            continue
        posts.append({
            "url": url,
            "title": d.get("title") or "",
            "snippet": d.get("selftext") or d.get("title") or "",
        })
    return posts, after


def harvest(
    domain: str,
    niche: str,
    *,
    keywords: list[str] | None = None,
    subreddits: list[str] | None = None,
    max_results: int = 20,
    max_age_days: int | None = 14,
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
    subs = [s.strip().lstrip("r/") for s in (subreddits or []) if s.strip()]
    if not subs:
        subs = ["all"]

    sub_idx = int(cursor.get("sub_index") or 0) % len(subs)
    mode = cursor.get("mode") or "new"
    after = cursor.get("after")
    term_idx = int(cursor.get("term_index") or 0)

    sub = subs[sub_idx]
    term = terms[term_idx % len(terms)] if terms else niche

    if mode == "new":
        url = f"https://www.reddit.com/r/{sub}/new.json?limit={PER_PAGE}"
        if after:
            url += f"&after={urllib.parse.quote(str(after))}"
        tid = f"reddit|new|{sub}"
    else:
        q = urllib.parse.quote(term)
        url = (
            f"https://www.reddit.com/r/{sub}/search.json?q={q}&restrict_sr=1"
            f"&sort=new&limit={PER_PAGE}"
        )
        if after:
            url += f"&after={urllib.parse.quote(str(after))}"
        tid = f"reddit|search|{sub}|{term}"

    plog_verbose("scan", "reddit_fetch", url=truncate(url, 200), template_id=tid)
    data = _fetch_json(url)
    posts, next_after = _posts_from_listing(data)

    leads: list[dict] = []
    seen: set[str] = set()
    for p in posts:
        key = url_key(p["url"])
        if key in skip_keys or key in seen:
            continue
        seen.add(key)
        lead = make_lead(
            url=p["url"], domain="reddit.com", title=p["title"], snippet=p["snippet"],
            platform="reddit.com", platform_weight=0.95, credibility_tier=1,
            opp_type="qa_community", context="reddit_api", terms=terms,
        )
        if lead is None:
            continue
        leads.append(lead)
        if len(leads) >= max_results:
            break

    new_cursor = dict(cursor)
    if next_after:
        new_cursor["after"] = next_after
        new_cursor["sub_index"] = sub_idx
        new_cursor["mode"] = mode
        new_cursor["term_index"] = term_idx
    else:
        new_cursor["after"] = None
        if mode == "new":
            new_cursor["mode"] = "search"
            new_cursor["term_index"] = term_idx
        else:
            new_cursor["mode"] = "new"
            new_cursor["term_index"] = (term_idx + 1) % max(len(terms), 1)
            new_cursor["sub_index"] = (sub_idx + 1) % len(subs)

    stats = {tid: len(leads)}
    if not leads and not posts:
        return STATUS_EMPTY, [], new_cursor, stats
    return STATUS_OK, leads[:max_results], new_cursor, stats
