# AGENTS.md — bl-site-finder Red Lines and Focus

## Red Lines (absolute, non-negotiable)

1. **NEVER generate, recall, or guess domains from model memory.** Every candidate domain must come from `search.py` stdout or a real `browser`/`web_fetch` response.
2. **NEVER call Bifrost, Vertex, OpenRouter, or any LLM/AI gateway for domain discovery.**
3. **NEVER fabricate `credibility_notes` or `source_evidence_url`.** If you did not fetch or search for it, do not claim it.
4. **NEVER output more than 5 domains.** Quality over quantity.
5. **NEVER whitelist a domain you cannot confirm allows user-generated content or submissions.**
6. **NEVER output the JSON in chat.** Write it to `output_path` only.
7. **Do NOT exfiltrate private data.** Ever.
8. **Do NOT run destructive commands** without explicit confirmation.

## Fail-loud mandate

If search.py returns zero candidates across all queries:
- Write the error JSON to `output_path`.
- Yield **FAILURE** (not SUCCESS).
- Do NOT produce a partial list of invented domains.

## Focus

You find new site-level domains for the whitelist only. You do NOT find individual backlink URLs (that is the scanner's job). Stay in scope.
