# AGENTS.md - Minimal Agent Rules

## Red Lines
- Don't exfiltrate private data. Ever.
- Don't run destructive commands without asking.
- Don't use exec, web_search, web_fetch, or browser — file read/write only.
- Don't return gate JSON in chat — write `gate_result.json` only.

## Focus
Score gate batch per SOUL.md. Yield SUCCESS.
