#!/usr/bin/env python3
"""
Tiered search skill for bl-finder and bl-competitor.

Provider chain (tried in order):
  1. DuckDuckGo html  – GET  https://html.duckduckgo.com/html/?q=   (primary, fast)
  2. DuckDuckGo lite  – POST https://lite.duckduckgo.com/lite/      (DDG fallback)
  3. SearXNG mirrors  – JSON endpoint /search?q=..&format=json       (always-available fallback; built-in list + BL_SEARXNG_MIRRORS override)

Rate-limit survival:
  - HTTP-200-but-empty is NOT retried with full backoff. Provider is advanced immediately.
  - DDG throttle/challenge pages detected; single cooldown applied instead of deepening the block.
  - Small jitter pacing between each provider call.
  - Optional in-run query cache (--cache <path>) so same query is never re-fetched within a run.
  - SearXNG is an always-on fallback (built-in mirror list) — DuckDuckGo stays primary.

Freshness filter: pass --freshness day|week|month to prefer recent results (optional, no hard default).
Maps to DuckDuckGo df=d|w|m parameter. NOTE: hard freshness filters often return empty on site: queries;
prefer no freshness and rank by recency instead.

Fail-loud: if every provider fails after retries, exits nonzero and
prints SEARCH_UNAVAILABLE: <last errors> to stderr. Never returns fabricated results.

CLI usage:
  python3 search.py --query "site:reddit.com crypto wallets" [--max 10] [--freshness week] [--cache /tmp/search-cache.json] [--json-out /path/out.json]

Env overrides:
  BL_SEARXNG_MIRRORS   comma-separated SearXNG base URLs (replaces built-in list when set)
  BL_SEARCH_TIMEOUT    per-request timeout in seconds (default 12)
  BL_SEARCH_RETRIES    max HTTP-error retries per provider (default 2)
  BL_SEARCH_COOLDOWN   seconds to wait when throttle detected (default 8)
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import TypedDict

_PIPELINE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pipeline"))
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)
from pipeline_log import plog_trace, truncate  # noqa: E402


class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str
    source_engine: str


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Built-in SearXNG mirror list — always available as fallback, no env required.
# Override completely with BL_SEARXNG_MIRRORS (comma-separated).
_BUILTIN_SEARXNG_MIRRORS: list[str] = [
    "https://paulgo.io",
    "https://searx.be",
    "https://search.inetol.net",
    "https://searxng.world",
]

FRESHNESS_MAP: dict[str, str] = {
    "day": "d",
    "week": "w",
    "month": "m",
}

DEFAULT_TIMEOUT = int(os.environ.get("BL_SEARCH_TIMEOUT", "12"))
DEFAULT_RETRIES = int(os.environ.get("BL_SEARCH_RETRIES", "1"))  # SearXNG fallback: fail fast
DEFAULT_COOLDOWN = float(os.environ.get("BL_SEARCH_COOLDOWN", "8"))  # throttle cooldown
# html/lite DDG endpoints are often blocked from WSL/home IPs; skip by default to avoid ~36s/query stalls.
ENABLE_DDG_HTML = os.environ.get("BL_ENABLE_DDG_HTML", "0").lower() in ("1", "true", "yes")

USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


def _pace() -> None:
    """Small jitter pause between provider calls to reduce throttling."""
    time.sleep(random.uniform(0.3, 0.8))


def _http_error_backoff(attempt: int) -> None:
    """Backoff only for real HTTP errors, not for empty results."""
    delay = (2 ** attempt) + random.uniform(0, 0.5)
    time.sleep(delay)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

_DDG_REDIRECT_RE = re.compile(r"[?&]uddg=([^&]+)", re.IGNORECASE)
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "ref", "fbclid", "gclid"}


def unwrap_ddg_redirect(url: str) -> str:
    """Unwrap DuckDuckGo /l/?uddg=<encoded> redirect links."""
    m = _DDG_REDIRECT_RE.search(url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return url


def strip_tracking(url: str) -> str:
    """Remove common tracking query parameters from a URL."""
    try:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        clean_qs = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        new_query = urllib.parse.urlencode(clean_qs, doseq=True)
        return parsed._replace(query=new_query).geturl()
    except Exception:
        return url


def normalize_url(url: str) -> str:
    url = unwrap_ddg_redirect(url)
    url = strip_tracking(url)
    return url.rstrip("/")


# ---------------------------------------------------------------------------
# Throttle detection
# ---------------------------------------------------------------------------

_DDG_THROTTLE_MARKERS = [
    "duckduckgo.com/bngp",
    "anomalous traffic",
    "bots use duckduckgo",
    "select all squares",
    "unusual traffic",
    "captcha",
    "challenge",
    "blocked",
    "unusual activity",
]


def is_ddg_throttled(raw: bytes) -> bool:
    """Return True if DDG response looks like a throttle/challenge page."""
    if not raw or len(raw) < 100:
        return True
    text = raw[:4096].decode("utf-8", errors="replace").lower()
    return any(m in text for m in _DDG_THROTTLE_MARKERS)


# ---------------------------------------------------------------------------
# HTTP fetch helpers (isolated so tests can monkey-patch)
# ---------------------------------------------------------------------------

def _http_get(url: str, *, headers: dict[str, str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _random_ua())
    req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8")
    req.add_header("Accept-Language", "en-US,en;q=0.5")
    req.add_header("Accept-Encoding", "gzip, deflate")
    req.add_header("Connection", "keep-alive")
    req.add_header("Upgrade-Insecure-Requests", "1")
    req.add_header("DNT", "1")
    req.add_header("Sec-Fetch-Dest", "document")
    req.add_header("Sec-Fetch-Mode", "navigate")
    req.add_header("Sec-Fetch-Site", "none")
    req.add_header("Sec-Fetch-User", "?1")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status not in (200, 301, 302):
            raise ValueError(f"HTTP {resp.status}")
        content = resp.read()
        if resp.info().get("Content-Encoding") == "gzip":
            try:
                content = gzip.decompress(content)
            except Exception:
                pass
        return content


def _http_post(url: str, data: dict[str, str], *, headers: dict[str, str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=encoded)
    req.add_header("User-Agent", _random_ua())
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8")
    req.add_header("Accept-Language", "en-US,en;q=0.5")
    req.add_header("Accept-Encoding", "gzip, deflate")
    req.add_header("Connection", "keep-alive")
    req.add_header("Upgrade-Insecure-Requests", "1")
    req.add_header("DNT", "1")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status not in (200, 301, 302):
            raise ValueError(f"HTTP {resp.status}")
        content = resp.read()
        if resp.info().get("Content-Encoding") == "gzip":
            try:
                content = gzip.decompress(content)
            except Exception:
                pass
        return content


# ---------------------------------------------------------------------------
# Parsers (pure functions — no network; importable by tests)
# ---------------------------------------------------------------------------

def parse_searxng_json(raw: bytes) -> list[SearchResult]:
    """Parse SearXNG JSON response bytes into SearchResult list."""
    data = json.loads(raw)
    out: list[SearchResult] = []
    for item in data.get("results", []):
        url = item.get("url", "")
        if not url:
            continue
        out.append(SearchResult(
            title=item.get("title", ""),
            url=normalize_url(url),
            snippet=item.get("content", ""),
            source_engine="searxng",
        ))
    return out


def parse_ddg_lite_html(raw: bytes) -> list[SearchResult]:
    """Parse DuckDuckGo lite HTML response bytes into SearchResult list."""
    text = raw.decode("utf-8", errors="replace")
    out: list[SearchResult] = []
    link_re = re.compile(r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_re = re.compile(r'class="result-snippet"[^>]*>(.*?)</td>', re.DOTALL)
    links = link_re.findall(text)
    snippets = snippet_re.findall(text)
    for i, (href, title_html) in enumerate(links):
        url = normalize_url(href)
        title = re.sub(r"<[^>]+>", "", title_html).strip()
        snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
        if url:
            out.append(SearchResult(title=title, url=url, snippet=snippet, source_engine="ddg_lite"))
    return out


def parse_ddg_html(raw: bytes) -> list[SearchResult]:
    """Parse DuckDuckGo HTML response bytes into SearchResult list."""
    text = raw.decode("utf-8", errors="replace")
    out: list[SearchResult] = []
    link_re = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snip_re = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
    links = link_re.findall(text)
    snippets = snip_re.findall(text)
    for i, (href, title_html) in enumerate(links):
        url = normalize_url(href)
        title = re.sub(r"<[^>]+>", "", title_html).strip()
        snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
        if url:
            out.append(SearchResult(title=title, url=url, snippet=snippet, source_engine="ddg_html"))
    return out


# ---------------------------------------------------------------------------
# Provider implementations (empty result = advance immediately, no backoff)
# ---------------------------------------------------------------------------

def _try_ddg_html(
    query: str,
    timeout: int,
    retries: int,
    freshness: str | None = None,
    cooldown: float = DEFAULT_COOLDOWN,
) -> tuple[list[SearchResult], bool]:
    """
    Returns (results, throttled).
    Empty results with throttle marker -> throttled=True.
    Empty results without throttle marker -> throttled=False (genuine empty).
    Both advance immediately without full backoff.
    """
    params: dict[str, str] = {"q": query}
    if freshness and freshness in FRESHNESS_MAP:
        params["df"] = FRESHNESS_MAP[freshness]
    url = f"https://html.duckduckgo.com/html/?{urllib.parse.urlencode(params)}"
    _pace()
    for attempt in range(retries + 1):
        try:
            raw = _http_get(url, timeout=timeout)
            if is_ddg_throttled(raw):
                time.sleep(cooldown)
                return [], True
            results = parse_ddg_html(raw)
            if results:
                return results, False
            # HTTP 200 but empty results — advance without backoff
            return [], False
        except Exception:
            if attempt < retries:
                _http_error_backoff(attempt)
    return [], False


def _try_ddg_lite(
    query: str,
    timeout: int,
    retries: int,
    freshness: str | None = None,
    cooldown: float = DEFAULT_COOLDOWN,
) -> tuple[list[SearchResult], bool]:
    """Returns (results, throttled)."""
    post_data: dict[str, str] = {"q": query}
    if freshness and freshness in FRESHNESS_MAP:
        post_data["df"] = FRESHNESS_MAP[freshness]
    _pace()
    for attempt in range(retries + 1):
        try:
            raw = _http_post("https://lite.duckduckgo.com/lite/", post_data, timeout=timeout)
            if is_ddg_throttled(raw):
                time.sleep(cooldown)
                return [], True
            results = parse_ddg_lite_html(raw)
            if results:
                return results, False
            return [], False
        except Exception:
            if attempt < retries:
                _http_error_backoff(attempt)
    return [], False


def _try_searxng(
    query: str,
    mirror: str,
    timeout: int,
    retries: int,
) -> list[SearchResult]:
    url = f"{mirror.rstrip('/')}/search?q={urllib.parse.quote_plus(query)}&format=json&language=en"
    _pace()
    for attempt in range(retries + 1):
        try:
            raw = _http_get(url, timeout=timeout)
            results = parse_searxng_json(raw)
            if results:
                return results
            return []
        except Exception:
            if attempt < retries:
                _http_error_backoff(attempt)
    return []


# ---------------------------------------------------------------------------
# In-run query cache
# ---------------------------------------------------------------------------

_MEMORY_CACHE: dict[str, dict] = {}


def _cache_key(query: str, freshness: str | None) -> str:
    return f"{query}|{freshness or ''}"


def _load_cache(cache_path: str | None) -> None:
    """Load disk cache into memory cache."""
    if not cache_path or not os.path.isfile(cache_path):
        return
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _MEMORY_CACHE.update(data)
    except Exception:
        pass


def _save_cache(cache_path: str | None) -> None:
    """Persist memory cache to disk."""
    if not cache_path:
        return
    try:
        os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(_MEMORY_CACHE, f, ensure_ascii=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------

def search(
    query: str,
    *,
    max_results: int = 10,
    freshness: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    cooldown: float = DEFAULT_COOLDOWN,
    cache_path: str | None = None,
    raise_on_failure: bool = True,
) -> dict:
    """
    Run the tiered search. Returns:
      {"status": "ok", "query": ..., "freshness": ..., "results": [...]}
    or on total failure:
      - raises SystemExit(1) when raise_on_failure=True (CLI default)
      - returns {"status": "error", ..., "results": [], "errors": [...]} when False

    freshness: optional "day"/"week"/"month" — do NOT use as a hard default.
               Hard freshness filters return empty on site: queries and skip platforms.
    cache_path: if set, results are cached so the same query is not re-fetched within a run.
    """
    # Check in-run cache first
    if cache_path:
        _load_cache(cache_path)
    ck = _cache_key(query, freshness)
    if ck in _MEMORY_CACHE:
        cached = _MEMORY_CACHE[ck]
        plog_trace(
            "search", "cache_hit",
            query=truncate(query, 200),
            raw=len(cached.get("results") or []),
        )
        return cached

    errors: list[str] = []
    seen_urls: set[str] = set()
    collected: list[SearchResult] = []
    ddg_throttled = False

    def _merge(results: list[SearchResult]) -> None:
        for r in results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                collected.append(r)

    # Tier 0: ddgs library (search_tool.py — primary, avoids HTML scrape blocks)
    timelimit_ddgs: str | None = None
    if freshness and freshness in FRESHNESS_MAP:
        timelimit_ddgs = {"day": "d", "week": "w", "month": "m"}.get(freshness)
    try:
        import search_tool as _st  # noqa: E402 — same directory

        mode = "site" if "site:" in query.lower() else "open"
        ddgs_hits = _st.search(
            query,
            max_results=max_results,
            timelimit=timelimit_ddgs,
            mode=mode,
        )
        for hit in ddgs_hits:
            if not isinstance(hit, dict):
                continue
            _merge([SearchResult(
                title=hit.get("title") or "",
                url=hit.get("url") or "",
                snippet=hit.get("snippet") or "",
                source_engine="ddgs",
            )])
    except Exception as e:
        errors.append(f"ddgs: {e}")

    if collected:
        engines = sorted({r.get("source_engine") or "unknown" for r in collected})
        plog_trace(
            "search", "provider_ok",
            query=truncate(query, 200), providers=",".join(engines), raw=len(collected),
        )

    if len(collected) >= max_results:
        result = {"status": "ok", "query": query, "freshness": freshness, "results": collected[:max_results]}
        _MEMORY_CACHE[ck] = result
        _save_cache(cache_path)
        return result

    # Tier 1/2: DuckDuckGo html + lite (opt-in; often blocked from home/WSL IPs)
    if ENABLE_DDG_HTML:
        try:
            res, throttled = _try_ddg_html(query, timeout, retries, freshness=freshness, cooldown=cooldown)
            if throttled:
                ddg_throttled = True
                errors.append("ddg_html: throttled/challenge")
            elif res:
                _merge(res)
            # empty but not throttled: advance immediately (no backoff)
        except Exception as e:
            errors.append(f"ddg_html: {e}")

        if len(collected) >= max_results:
            result = {"status": "ok", "query": query, "freshness": freshness, "results": collected[:max_results]}
            _MEMORY_CACHE[ck] = result
            _save_cache(cache_path)
            return result

        # Tier 2: DuckDuckGo lite (skip if already throttled — same network/IP)
        if not ddg_throttled:
            try:
                res, throttled = _try_ddg_lite(query, timeout, retries, freshness=freshness, cooldown=cooldown)
                if throttled:
                    ddg_throttled = True
                    errors.append("ddg_lite: throttled/challenge")
                elif res:
                    _merge(res)
            except Exception as e:
                errors.append(f"ddg_lite: {e}")

            if len(collected) >= max_results:
                result = {"status": "ok", "query": query, "freshness": freshness, "results": collected[:max_results]}
                _MEMORY_CACHE[ck] = result
                _save_cache(cache_path)
                return result

    # Tier 3: SearXNG — always-available fallback (not opt-in).
    # Engaged when DuckDuckGo is throttled OR empty. DuckDuckGo is still tried first.
    mirrors_env = os.environ.get("BL_SEARXNG_MIRRORS", "").strip()
    if mirrors_env:
        mirrors = [m.strip() for m in mirrors_env.split(",") if m.strip()]
    else:
        mirrors = list(_BUILTIN_SEARXNG_MIRRORS)
    random.shuffle(mirrors)
    for mirror in mirrors:
        try:
            res = _try_searxng(query, mirror, timeout, retries)
            if res:
                _merge(res)
                if len(collected) >= max_results:
                    break
        except Exception as e:
            errors.append(f"searxng/{mirror}: {e}")

    if collected:
        engines = sorted({r.get("source_engine") or "unknown" for r in collected})
        plog_trace(
            "search", "provider_ok",
            query=truncate(query, 200), providers=",".join(engines), raw=len(collected),
        )
        result = {"status": "ok", "query": query, "freshness": freshness, "results": collected[:max_results]}
        _MEMORY_CACHE[ck] = result
        _save_cache(cache_path)
        return result

    # All providers failed
    err_summary = "; ".join(errors) if errors else "all providers returned empty"
    plog_trace("search", "all_failed", query=truncate(query, 200), errors=truncate(err_summary, 300))
    if not raise_on_failure:
        return {
            "status": "error",
            "query": query,
            "freshness": freshness,
            "results": [],
            "errors": errors,
        }
    print(f"SEARCH_UNAVAILABLE: {err_summary}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Tiered search (DuckDuckGo first; SearXNG always-on fallback)")
    parser.add_argument("--query", required=True, help="Search query string")
    parser.add_argument("--max", type=int, default=10, dest="max_results", help="Maximum results (default: 10)")
    parser.add_argument(
        "--freshness",
        choices=["day", "week", "month"],
        default=None,
        help="Prefer results from: day (last 24h), week (last 7d), month (last 30d). "
             "NOTE: hard freshness on site: queries often returns empty; prefer no flag + recency ranking.",
    )
    parser.add_argument("--cache", dest="cache_path", default=None, help="Cache file path (avoids re-fetching same query within a run)")
    parser.add_argument("--json-out", dest="json_out", help="Write JSON output to this file path")
    args = parser.parse_args()

    result = search(args.query, max_results=args.max_results, freshness=args.freshness, cache_path=args.cache_path)
    output = json.dumps(result, indent=2)
    print(output)
    if args.json_out:
        with open(args.json_out, "w") as fh:
            fh.write(output)


if __name__ == "__main__":
    main()
