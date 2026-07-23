#!/usr/bin/env python3
"""rss_sitemap.py — Generic RSS/Atom feed poller for any whitelist domain."""
from __future__ import annotations

import re
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_SEARCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PIPELINE_DIR = os.path.abspath(os.path.join(_SEARCH_DIR, "..", "pipeline"))
for _p in (_SEARCH_DIR, _PIPELINE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from discover import url_key  # noqa: E402
from pipeline_log import plog_verbose, truncate  # noqa: E402
from harvesters._common import make_lead  # noqa: E402

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_BLOCKED = "blocked"

FEED_PATHS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/blog/feed", "/index.xml")


def _probe_feed(domain: str) -> str | None:
    base = f"https://{domain}"
    for path in FEED_PATHS:
        url = base + path
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "backlink-farmer/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                body = resp.read(8000)
                if b"<rss" in body or b"<feed" in body or "xml" in ctype:
                    return url
        except Exception:
            continue
    return None


def _parse_feed(xml_bytes: bytes, domain: str) -> list[dict]:
    items: list[dict] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    for item in root.iter():
        tag = item.tag.split("}")[-1] if "}" in item.tag else item.tag
        if tag not in ("item", "entry"):
            continue
        title = ""
        link = ""
        desc = ""
        for child in item:
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if ctag == "title" and child.text:
                title = child.text.strip()
            elif ctag == "link":
                link = (child.text or child.get("href") or "").strip()
            elif ctag in ("description", "summary", "content") and child.text:
                desc = child.text.strip()[:400]
        if link and domain in link:
            items.append({"url": link, "title": title, "snippet": desc or title})
    return items


def harvest(
    domain: str,
    niche: str,
    *,
    keywords: list[str] | None = None,
    max_results: int = 20,
    skip_keys: set[str] | None = None,
    cursor: dict | None = None,
    **kwargs,
) -> tuple[str, list[dict], dict, dict[str, int]]:
    skip_keys = skip_keys or set()
    cursor = dict(cursor or {})
    dom = domain.lower().strip().lstrip("www.")

    feed_url = cursor.get("feed_url")
    if not feed_url:
        feed_url = _probe_feed(dom)
        if feed_url:
            cursor["feed_url"] = feed_url
            plog_verbose("scan", "rss_probe_ok", domain=dom, feed_url=truncate(feed_url, 120))
        else:
            return STATUS_EMPTY, [], cursor, {}

    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "backlink-farmer/1.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            xml_bytes = resp.read(500_000)
    except Exception as exc:
        plog_verbose("scan", "rss_fetch_error", error=str(exc)[:120])
        return STATUS_BLOCKED, [], cursor, {}

    items = _parse_feed(xml_bytes, dom)
    last_seen = set(cursor.get("seen_urls") or [])
    leads: list[dict] = []
    new_seen = set(last_seen)

    for item in items:
        url = item["url"]
        key = url_key(url)
        if key in skip_keys or key in last_seen:
            continue
        new_seen.add(key)
        lead = make_lead(
            url=url, domain=dom, title=item["title"], snippet=item["snippet"],
            platform=dom, platform_weight=0.7, credibility_tier=3,
            context="rss_feed", posting_action="reply",
        )
        if lead is None:
            continue
        leads.append(lead)
        if len(leads) >= max_results:
            break

    new_cursor = {**cursor, "seen_urls": list(new_seen)[-500:]}
    stats = {"rss|feed": len(leads)}
    if not leads:
        return STATUS_EMPTY, [], new_cursor, stats
    return STATUS_OK, leads, new_cursor, stats
