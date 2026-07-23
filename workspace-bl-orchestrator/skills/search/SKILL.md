# Search Skill

Deterministic tiered search for bl-finder and bl-competitor. The ONLY allowed search path.

## `search.py` — tiered search

```bash
python3 skills/search/search.py --query "site:reddit.com crypto wallet" [--max 10] [--freshness week] [--cache /tmp/search-cache.json] [--json-out /tmp/results.json]
```

Output JSON (stdout):
```json
{
  "status": "ok",
  "query": "site:reddit.com crypto wallet",
  "freshness": null,
  "results": [
    {"title": "...", "url": "https://...", "snippet": "...", "source_engine": "ddg_html"}
  ]
}
```

### Provider chain

1. **ddgs library** (`search_tool.py`) — primary; avoids HTML scrape blocks.
2. **DuckDuckGo html** — legacy fallback.
3. **DuckDuckGo lite** — DDG fallback when html is empty.
4. **SearXNG mirrors** — always-on fallback when DDG empty/throttled.

**Dependency:** `pip install ddgs`

### Companion tools (backlink discovery)

| Script | Role |
|--------|------|
| `search_tool.py` | Standalone ddgs search (`--mode site\|open`) |
| `read_tool.py` | Jina Reader + trafilatura fallback (`JINA_API_KEY` in openclaw.json) |
| `lead_enrich.py` | Snippet-trust for Reddit; Jina enrich for other sites |
| `reddit_scan.py` | Subreddit-targeted Reddit scans (`config_json.subreddits`) |
| `resolve_url.py` | Aggregator URL unwrap (Google News wrappers) |

### Rate-limit survival

- **Empty ≠ retryable**: HTTP 200 with zero results advances to next provider immediately (no backoff waste).
- **Throttle detection**: DDG challenge/CAPTCHA pages detected; single `BL_SEARCH_COOLDOWN`-second pause instead of rapid retries that deepen throttling.
- **Pacing**: small jitter (0.3–0.8 s) before each provider call.
- **In-run cache**: `--cache <path>` caches results to disk so the same query is never re-fetched within a run.
- **SearXNG fallback**: always available (no env required) when DuckDuckGo throttles.

### Freshness filter

`--freshness day|week|month` applies DDG `df=d|w|m`. **Do NOT use as a hard default.**
Hard freshness on `site:` queries returns empty and silently skips platforms.
Prefer no freshness flag + recency ranking in discover.py.

### Environment overrides

| Variable | Default | Description |
|---|---|---|
| `BL_SEARXNG_MIRRORS` | built-in list | Comma-separated SearXNG base URLs (replaces built-in list when set) |
| `BL_SEARCH_TIMEOUT` | `12` | Per-request timeout (seconds) |
| `BL_SEARCH_RETRIES` | `2` | Max HTTP-error retries per provider |
| `BL_SEARCH_COOLDOWN` | `8` | Seconds to wait when throttle detected |

### Fail-loud contract

If every provider fails: exits 1, prints `SEARCH_UNAVAILABLE: <errors>` to stderr, nothing to stdout. Never returns fabricated results.

---

## `discover.py` — batch discovery helper (use this in bl-finder)

Replaces the manual per-platform search/curl/web_fetch loop. The agent makes **ONE** call instead of dozens.

```bash
python3 skills/search/discover.py \
  --queue $RUN_DIR/discovery/platform_queue.json \
  --niche "memecoin tracker" \
  --target 12 \
  --max-per-platform 5 \
  --out $RUN_DIR/discovery/candidates.json \
  [--cache /tmp/search-cache.json] \
  [--skip-urls recent_sites.json] \
  [--no-liveness]   # skip curl check (testing only)
```

### What it does

1. Iterates platform queue tier-first (discussion/forum platforms first).
2. Runs 1 search query per platform via `search.py` (2nd query if first empty). Stops early at `--target`.
3. Dedupes by normalized URL across platforms.
4. Verifies liveness concurrently with `curl -L` — **follows redirects, accepts final 2xx**. This is the fix for Reddit/X returning 301.
5. **Content from snippet** — uses search `title` + `snippet` as `target_title`/`target_excerpt`. Verified real content. Reddit/X block page fetches (403/JS-wall); snippet is the only reliable source.
6. Optional `trafilatura` for normal (non-Reddit/X) sites to get richer excerpts.
7. Ranks by `platform_weight * 0.5 + recency_score * 0.3 + type_bonus * 0.2`. Fresh discussions float first.
8. Writes `candidates.json`. **Fail-loud** if zero live candidates.

### Output format

```json
{
  "status": "ok",
  "niche": "memecoin tracker",
  "candidates": [
    {
      "url": "https://reddit.com/r/crypto/comments/abc/...",
      "submission_url": "https://reddit.com/r/crypto/comments/abc/...",
      "domain": "reddit.com",
      "type": "qa_community",
      "target_title": "Best memecoin tracking sites?",
      "target_excerpt": "I've been looking for a good way to track meme coin transactions...",
      "opportunity_freshness": "~2 days ago",
      "platform": "reddit.com",
      "credibility_tier": 1,
      "platform_weight": 0.95,
      "recency_score": 0.75,
      "rank_score": 0.87,
      "http_ok": true,
      "needs_browser": false,
      "source_engine": "ddg_html"
    }
  ]
}
```

### Reddit/X fetch rules

- **Never fetch Reddit/X pages** — they 403 or JS-wall. `target_title`/`target_excerpt` come from the search snippet (real content, verified).
- **curl -L** follows Reddit's 301 trailing-slash redirect → final 200 = alive.
- `needs_browser: true` means the snippet was thin and a browser render could help (set for tier-3/4 sites with short snippets).

### Important: browser is NOT for search

The `browser` tool gets CAPTCHA'd by DuckDuckGo when used for search. Use `search.py` (via discover.py) for all search queries. Browser is only for rendering individual target pages (content extraction) when `needs_browser: true`.

---

## Testability

All parsing and ranking functions are importable and pure — no network:

```python
from skills.search.search import parse_ddg_html, is_ddg_throttled, FRESHNESS_MAP
from skills.search.discover import parse_recency_hours, recency_score, rank_score, BLOCKED_FETCH_DOMAINS
```

Network calls (`_http_get`, `_http_post`, `_check_url`, `_extract_via_trafilatura`) are isolated behind named functions and can be monkey-patched in tests.
