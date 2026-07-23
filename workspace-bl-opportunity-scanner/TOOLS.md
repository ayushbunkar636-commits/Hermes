# TOOLS.md — bl-opportunity-scanner

## Site-scoped search (REQUIRED — must include site: operator)

```bash
python3 /home/bhard/.openclaw-backlink/workspace-bl-orchestrator/skills/search/search.py \
  --query "site:<domain> <niche>" \
  --max 10 \
  [--cache /tmp/bl-scanner-cache.json]
```

Every query MUST use `site:<domain>`. No open-web queries allowed.

## URL liveness check

```bash
curl -L -o /dev/null -s -w "%{http_code}" "<url>"
```

Accept final status 2xx. `-L` required to follow redirects (Reddit, X return 301).

## Page content

```bash
# Fast (most sites):
web_fetch "<url>"

# Bot-blocked (fallback):
browser open "<url>"
browser snapshot
```

**Do NOT fetch Reddit/X pages** — they return 403 or JS-wall. Use snippet from search.

## Rules
- `search.py` is your ONLY search path. Do not use `web_search`.
- Every search query must use `site:` scoping.
- Never call any LLM or completion endpoint.
