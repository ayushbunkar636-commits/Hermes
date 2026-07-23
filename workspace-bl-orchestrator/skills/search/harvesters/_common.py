"""Shared helpers for harvest adapters."""
from __future__ import annotations

import re
import urllib.parse
from typing import Optional

from discover import extract_domain, url_key, niche_overlap_score, recency_score, parse_recency_hours  # noqa: E402
from lang_filter import is_probably_english  # noqa: E402

DISCUSSION_TYPES = frozenset({"forum", "qa_community", "comment"})


def freshness_str(hours: float | None) -> str:
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


def make_lead(
    *,
    url: str,
    domain: str,
    title: str,
    snippet: str,
    platform: str,
    platform_weight: float = 0.65,
    credibility_tier: int = 3,
    opp_type: str = "forum",
    context: str = "",
    terms: list[str] | None = None,
    posting_action: str = "reply",
) -> Optional[dict]:
    if not is_probably_english(title, snippet):
        return None
    hours = parse_recency_hours(f"{title} {snippet}")
    rel = niche_overlap_score(title, snippet, terms) if terms else None
    key = url_key(url)
    return {
        "url": url,
        "url_key": key,
        "submission_url": url,
        "domain": extract_domain(url) or domain,
        "type": opp_type,
        "target_title": title,
        "target_excerpt": snippet,
        "opportunity_context": context,
        "opportunity_freshness": freshness_str(hours),
        "posting_action": posting_action,
        "platform": platform,
        "platform_weight": platform_weight,
        "credibility_tier": credibility_tier,
        "relevance_score": rel,
        "recency_score": recency_score(hours),
    }


def extract_domains_from_text(text: str) -> list[str]:
    """Pull candidate domains from title/excerpt for graph-follow."""
    if not text:
        return []
    found = re.findall(r"https?://[^\s<>\"']+", text)
    out: list[str] = []
    for u in found:
        d = extract_domain(u)
        if d and d not in out:
            out.append(d)
    return out[:5]
