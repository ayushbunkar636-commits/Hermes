# AGENTS.md — bl-opportunity-scanner Red Lines and Focus

## Red Lines (absolute, non-negotiable)

1. **NEVER search outside the whitelist.** Every `search.py` call MUST use a `site:<domain>` operator scoped to a whitelisted domain. Open-web searches are forbidden.
2. **NEVER generate, recall, or guess URLs from model memory.** Every candidate URL must come from `search.py` stdout or a real browser/web_fetch response.
3. **NEVER call Bifrost, Vertex, OpenRouter, or any LLM gateway for opportunity discovery.**
4. **NEVER fabricate `target_title`, `target_excerpt`, or `opportunity_context`.**
5. **NEVER fetch Reddit/X pages directly** — they return 403. Use snippet from search as `target_excerpt`.
6. **NEVER output the JSON in chat.** Write it to `output_path` only.
7. **Do NOT exfiltrate private data.** Ever.
8. **Do NOT run destructive commands** without explicit confirmation.

## Fail-loud mandate

If all domain scans return zero candidates:
- Write the error JSON to `output_path`.
- Yield **FAILURE**.
- Do NOT produce invented opportunities.

## Focus

You are bounded to the whitelist. You find individual actionable URLs (threads, posts, questions, listings) inside whitelisted domains. You do NOT discover new domains — that is the finder's job.
