#!/usr/bin/env python3
"""
discover.py — Batch discovery helper for bl-finder.

Replaces the manual per-platform search/curl/web_fetch loop in the agent.
Does all heavy network work in one deterministic Python process so the agent
only needs to make ONE tool call instead of dozens.

Workflow:
  1. Load platform queue (from build_platform_queue.py output).
  2. Iterate platforms tier-first. Run 1 search query per platform (2nd if first empty).
     Stop early when --target verified candidates collected.
  3. Dedupe candidates by normalized URL across platforms.
  4. Verify liveness concurrently with curl -L (follow redirects). Accept final 2xx.
  5. Content: use search title+snippet as target_title/target_excerpt for discussion
     sites (Reddit/X block page fetches). Run trafilatura for normal sites if available.
  6. Rank by: platform_weight * 0.5 + recency_score * 0.3 + type_bonus * 0.2.
     Fresh discussions float to the top.
  7. Write ranked candidate JSON. Fail-loud if zero live candidates.

CLI:
  python3 discover.py \\
    --queue $RUN_DIR/discovery/platform_queue.json \\
    --niche "memecoin tracker" \\
    --target 12 \\
    --max-per-platform 5 \\
    --out $RUN_DIR/discovery/candidates.json \\
    [--cache /tmp/search-cache.json]

Output JSON:
  {"status": "ok", "niche": "...", "candidates": [{...}, ...]}
  or writes status:error and exits 1 on SEARCH_UNAVAILABLE.

Each candidate has:
  url, domain, submission_url, target_title, target_excerpt,
  opportunity_freshness, platform, credibility_tier, platform_weight,
  recency_score, type, http_ok, needs_browser, source_engine
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# Add search.py directory to path so we can import it
_SEARCH_DIR = os.path.dirname(__file__)
sys.path.insert(0, _SEARCH_DIR)

from search import search, normalize_url  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Domains that block page fetching (403/JS-wall). Use snippet-only for these.
BLOCKED_FETCH_DOMAINS = frozenset({
    "reddit.com", "www.reddit.com",
    "x.com", "twitter.com", "www.twitter.com",
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
    "linkedin.com", "www.linkedin.com",
})

DISCUSSION_TYPES = frozenset({"qa_community", "forum", "comment"})

# Recency patterns parsed from snippets/titles
_AGO_RE = re.compile(
    r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Recency scoring (pure, no network)
# ---------------------------------------------------------------------------

def parse_recency_hours(text: str) -> float | None:
    """
    Parse relative age from snippet/title text.
    Returns age in hours (lower = more recent), or None if not found.
    """
    m = _AGO_RE.search(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        mapping = {
            "second": 1 / 3600,
            "minute": 1 / 60,
            "hour": 1.0,
            "day": 24.0,
            "week": 168.0,
            "month": 720.0,
            "year": 8760.0,
        }
        return n * mapping.get(unit, 720.0)
    return None


def recency_score(hours_old: float | None) -> float:
    """
    Map age in hours to a 0-1 recency score (1.0 = posted now, 0.0 = very old).
    Unknown age gets neutral 0.5.
    """
    if hours_old is None:
        return 0.5
    if hours_old <= 2:
        return 1.0
    if hours_old <= 24:
        return 0.9
    if hours_old <= 72:
        return 0.75
    if hours_old <= 168:  # 1 week
        return 0.6
    if hours_old <= 720:  # 1 month
        return 0.4
    return 0.2


def rank_score(platform_weight: float, rec_score: float, opp_type: str) -> float:
    type_bonus = 0.1 if opp_type in DISCUSSION_TYPES else 0.0
    return (platform_weight * 0.5) + (rec_score * 0.3) + type_bonus * 0.2 + type_bonus * 0.1


# ---------------------------------------------------------------------------
# Liveness check (network — isolated via _check_url for tests)
# ---------------------------------------------------------------------------

def _check_url(url: str, timeout: int = 10) -> bool:
    """
    Check if a URL is live using curl -L (follow redirects).
    Returns True if final HTTP status is 2xx.
    """
    try:
        result = subprocess.run(
            ["curl", "-L", "-o", "/dev/null", "-s", "-w", "%{http_code}", "--max-time", str(timeout), url],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        code = result.stdout.strip()
        return code.startswith("2")
    except Exception:
        return False


def check_urls_concurrent(urls: list[str], max_workers: int = 6, timeout: int = 10) -> dict[str, bool]:
    """Check liveness for a list of URLs concurrently. Returns {url: is_live}."""
    results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_check_url, url, timeout): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception:
                results[url] = False
    return results


# ---------------------------------------------------------------------------
# Content extraction (network — isolated for tests)
# ---------------------------------------------------------------------------

def _is_blocked_domain(url: str) -> bool:
    """Return True if the domain is known to block page fetching."""
    try:
        domain = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        return domain in BLOCKED_FETCH_DOMAINS or ("www." + domain) in BLOCKED_FETCH_DOMAINS
    except Exception:
        return False


def _extract_via_trafilatura(url: str, timeout: int = 15) -> tuple[str, str]:
    """
    Run trafilatura on a normal (non-blocked) URL.
    Returns (title, excerpt) or ("", "") on failure.
    """
    try:
        result = subprocess.run(
            ["trafilatura", "-u", url, "--output-format", "txt", "--no-fallback"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        text = result.stdout.strip()
        if not text:
            return "", ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        title = lines[0][:200] if lines else ""
        excerpt = " ".join(lines[:5])[:500]
        return title, excerpt
    except Exception:
        return "", ""


def enrich_content(
    candidates: list[dict[str, Any]],
    use_trafilatura: bool = True,
    max_workers: int = 4,
) -> None:
    """
    Enrich candidates with richer target_title/target_excerpt where possible.
    For blocked domains: skip (keep snippet). For normal sites: try trafilatura.
    Modifies candidates in-place.
    """
    if not use_trafilatura:
        return

    def _enrich_one(cand: dict[str, Any]) -> None:
        url = cand.get("url", "")
        if _is_blocked_domain(url):
            cand["needs_browser"] = False
            return
        existing_excerpt = cand.get("target_excerpt", "")
        if existing_excerpt and len(existing_excerpt) >= 100:
            cand["needs_browser"] = False
            return
        title, excerpt = _extract_via_trafilatura(url)
        if title:
            cand["target_title"] = title
        if excerpt:
            cand["target_excerpt"] = excerpt
        cand["needs_browser"] = not bool(excerpt)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_enrich_one, candidates))


# ---------------------------------------------------------------------------
# Domain extraction
# ---------------------------------------------------------------------------

def extract_domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def url_key(url: str) -> str:
    return normalize_url(url).lower()


# ---------------------------------------------------------------------------
# Niche / keyword normalization (Farmer v2)
# ---------------------------------------------------------------------------

_TERM_SPLIT_RE = re.compile(r"[,/|;]+")


def clean_terms(niche: str = "", keywords: list[str] | None = None) -> list[str]:
    """Split niche/keywords on comma, slash, pipe; trim; dedupe case-insensitively."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in [niche or ""] + list(keywords or []):
        for part in _TERM_SPLIT_RE.split(str(raw)):
            t = part.strip()
            if not t or len(t) < 2:
                continue
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
    return out


def niche_overlap_score(title: str, excerpt: str, terms: list[str]) -> float:
    """Deterministic 0-10 relevance from keyword hits in title + excerpt."""
    if not terms:
        return 5.0
    blob = f"{title or ''} {excerpt or ''}".lower()
    if not blob.strip():
        return 3.0
    hits = 0
    for term in terms:
        t = term.lower().strip()
        if not t:
            continue
        if t in blob:
            hits += 1
            continue
        # Multi-word: all tokens must appear
        parts = t.split()
        if len(parts) > 1 and all(p in blob for p in parts):
            hits += 1
    if hits == 0:
        return 2.0
    ratio = hits / len(terms)
    return round(min(10.0, 3.0 + ratio * 7.0), 2)


# ---------------------------------------------------------------------------
# Main discovery function
# ---------------------------------------------------------------------------

def discover(
    queue: list[dict],
    niche: str,
    *,
    target: int = 12,
    max_per_platform: int = 5,
    cache_path: str | None = None,
    skip_urls: set[str] | None = None,
    use_trafilatura: bool = True,
    check_liveness: bool = True,
) -> list[dict[str, Any]]:
    """
    Run batch discovery over platform queue.
    Returns ranked list of candidate dicts.
    Raises SystemExit(1) with SEARCH_UNAVAILABLE if zero candidates found.
    """
    skip_keys = {url_key(u) for u in (skip_urls or set())}
    seen_keys: set[str] = set()
    raw_candidates: list[dict[str, Any]] = []

    for platform_entry in queue:
        if len(raw_candidates) >= target * 2:
            break

        domain = platform_entry.get("domain", "")
        tier = platform_entry.get("tier", 4)
        weight = float(platform_entry.get("weight", 0.55))
        plat_types = platform_entry.get("types", ["forum"])
        opp_type = plat_types[0] if plat_types else "forum"
        freshness_default = platform_entry.get("freshness", None)
        niche_queries: list[str] = platform_entry.get("niche_queries", [])

        if not niche_queries:
            niche_queries = [f"site:{domain} {niche}"]

        found_for_platform = 0

        for qi, query in enumerate(niche_queries[:3]):
            if found_for_platform >= max_per_platform:
                break

            # First query: no freshness (more reliable). Second query: use platform freshness.
            use_freshness = freshness_default if qi > 0 else None

            try:
                result = search(
                    query,
                    max_results=max_per_platform + 3,
                    freshness=use_freshness,
                    cache_path=cache_path,
                )
            except SystemExit:
                # search.py exited — this platform unavailable
                break

            for r in result.get("results", []):
                url = r.get("url", "")
                if not url:
                    continue
                key = url_key(url)
                if key in seen_keys or key in skip_keys:
                    continue
                # Deep URL check: must have a non-trivial path
                parsed = urllib.parse.urlparse(url)
                path = parsed.path.rstrip("/")
                if path in ("", "/"):
                    continue

                seen_keys.add(key)
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                hours = parse_recency_hours(title + " " + snippet)
                rec = recency_score(hours)

                freshness_str = "unknown"
                if hours is not None:
                    if hours < 2:
                        freshness_str = "~1 hour ago"
                    elif hours < 24:
                        freshness_str = f"~{int(hours)} hours ago"
                    elif hours < 168:
                        freshness_str = f"~{int(hours/24)} days ago"
                    elif hours < 720:
                        freshness_str = f"~{int(hours/168)} weeks ago"
                    else:
                        freshness_str = f"~{int(hours/720)} months ago"

                cand: dict[str, Any] = {
                    "url": url,
                    "submission_url": url,
                    "domain": extract_domain(url),
                    "type": opp_type,
                    "target_title": title,
                    "target_excerpt": snippet,
                    "opportunity_freshness": freshness_str,
                    "platform": domain,
                    "credibility_tier": tier,
                    "platform_weight": weight,
                    "recency_score": rec,
                    "rank_score": rank_score(weight, rec, opp_type),
                    "http_ok": True,
                    "needs_browser": False,
                    "source_engine": r.get("source_engine", ""),
                }
                raw_candidates.append(cand)
                found_for_platform += 1

            # If first query yielded nothing: run 2nd query with freshness as fallback
            if found_for_platform == 0 and qi == 0:
                continue  # loop to next query

    if not raw_candidates:
        print("SEARCH_UNAVAILABLE: discover.py found zero raw candidates across all platforms", file=sys.stderr)
        sys.exit(1)

    # Liveness + enrichment (Jina / snippet-trust — no curl drop on Reddit)
    if check_liveness:
        from lead_enrich import verify_and_enrich  # noqa: E402

        live: list[dict[str, Any]] = []
        for c in raw_candidates:
            ok, title, excerpt, _ = verify_and_enrich(
                c["url"], c.get("target_title") or "", c.get("target_excerpt") or "", min_words=0
            )
            if not ok:
                continue
            c["target_title"] = title
            c["target_excerpt"] = excerpt
            c["http_ok"] = True
            live.append(c)
        raw_candidates = live

    if not raw_candidates:
        print("SEARCH_UNAVAILABLE: discover.py: all candidates failed liveness check", file=sys.stderr)
        sys.exit(1)

    # Optional trafilatura enrichment for normal sites
    if use_trafilatura:
        enrich_content(raw_candidates)

    # Rank: fresh discussions first
    raw_candidates.sort(key=lambda c: c.get("rank_score", 0), reverse=True)

    return raw_candidates[:target * 2]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Batch discovery helper: search + verify + rank")
    parser.add_argument("--queue", required=True, help="Path to platform_queue.json")
    parser.add_argument("--niche", required=True, help="Niche/topic string")
    parser.add_argument("--target", type=int, default=12, help="Target number of verified candidates")
    parser.add_argument("--max-per-platform", type=int, default=5, dest="max_per_platform")
    parser.add_argument("--out", required=True, help="Output candidates JSON path")
    parser.add_argument("--cache", dest="cache_path", default=None, help="Search cache file path")
    parser.add_argument("--skip-urls", dest="skip_urls_path", default=None, help="JSON file with list of URLs to skip (burn-list)")
    parser.add_argument("--no-liveness", dest="no_liveness", action="store_true", help="Skip curl liveness check (faster, for testing)")
    parser.add_argument("--no-trafilatura", dest="no_trafilatura", action="store_true", help="Skip trafilatura enrichment")
    args = parser.parse_args()

    with open(args.queue, encoding="utf-8") as f:
        queue = json.load(f)

    skip_urls: set[str] = set()
    if args.skip_urls_path and os.path.isfile(args.skip_urls_path):
        with open(args.skip_urls_path, encoding="utf-8") as f:
            raw_skip = json.load(f)
        if isinstance(raw_skip, list):
            skip_urls = {str(u) for u in raw_skip}
        elif isinstance(raw_skip, dict):
            # Accept recent_sites.json format too
            for entry in raw_skip if isinstance(raw_skip, list) else []:
                if isinstance(entry, dict):
                    u = entry.get("submission_url") or entry.get("url")
                    if u:
                        skip_urls.add(str(u))

    candidates = discover(
        queue,
        args.niche,
        target=args.target,
        max_per_platform=args.max_per_platform,
        cache_path=args.cache_path,
        skip_urls=skip_urls,
        use_trafilatura=not args.no_trafilatura,
        check_liveness=not args.no_liveness,
    )

    output = {
        "status": "ok",
        "niche": args.niche,
        "candidates": candidates,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"DISCOVER_OK: {len(candidates)} candidates written to {args.out}")


if __name__ == "__main__":
    main()
