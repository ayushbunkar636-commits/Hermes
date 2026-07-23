#!/usr/bin/env python3
"""x_filter.py — Keep real X/Twitter threads; drop profile landing pages."""
from __future__ import annotations

import urllib.parse

_X_DOMAINS = frozenset({"x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"})


def is_x_domain(domain: str) -> bool:
    d = (domain or "").lower().strip().lstrip("www.")
    return d in _X_DOMAINS or d.endswith(".twitter.com")


def is_x_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        return host in _X_DOMAINS or host.endswith(".twitter.com")
    except Exception:
        return False


def is_x_thread_url(url: str) -> bool:
    """True when URL points at a specific tweet/thread (actionable reply target)."""
    if not is_x_url(url):
        return False
    path = urllib.parse.urlparse(url).path.lower()
    return "/status/" in path


def accept_x_url(url: str) -> bool:
    """Reject bare profile pages like x.com/handle or x.com/handle/posts."""
    if not is_x_url(url):
        return True
    return is_x_thread_url(url)
