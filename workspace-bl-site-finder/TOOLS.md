# TOOLS.md — bl-site-finder

## Search (primary tool)

```bash
python3 /home/bhard/.openclaw-backlink/workspace-bl-orchestrator/skills/search/search.py \
  --query "<your query>" \
  --max 10 \
  [--cache /tmp/bl-finder-cache.json]
```

Output: JSON with `results[]`, each having `url`, `title`, `snippet`.

## Page inspection

```bash
# Fast text fetch (most sites):
web_fetch "<url>"

# Bot-blocked sites (fallback):
browser open "<url>"
browser snapshot
```

## Rules
- `search.py` is your ONLY search path. Do not use `web_search`.
- `browser` is for inspecting individual candidate sites only, not for running searches.
- Never use any LLM or completion endpoint.
