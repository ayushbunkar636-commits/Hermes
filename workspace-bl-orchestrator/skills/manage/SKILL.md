# Skill: Manage Projects & Sources

Read this ONLY when the user asks to manage projects or sources (add/edit/pause/
resume/delete a project, list/status, inspect sources, scan now, find new sites,
scan one domain, set scan priority).
All actions run through ONE deterministic tool — no LLM logic, low cost.

**Adding a new project (preferred):** tell the user to run Telegram `/onboard` in
any group they control. That flow is fully offline (no LLM). `/cancel` aborts mid-wizard.
Steps: group id → URL → niche → name → **description (required)** → **extra source domains (recommended, skip ok)** → confirm.
Default whitelist (~8 sites from `platforms.json` tiers 1–2) is seeded automatically; extra domains are added on confirm.
**Telegram scoping is DB-only** — the plugin injects `PROJECT_URL` per group at runtime; onboarding does not edit `openclaw.json`.
Verify all bindings: `python3 .../project_telegram_scope.py verify-all`

Tool: `python3 ~/.openclaw-backlink/workspace-bl-orchestrator/skills/pipeline/manage_projects.py <cmd> [args]`

Terminal onboarding equivalent: `python3 ~/.openclaw-backlink/workspace-bl-orchestrator/skills/pipeline/onboard_backlink.py wizard`

Every command prints a single `OK: ...` or `ERROR: ...` line (plus JSON details).
Relay that result to the user. On `ERROR:`, tell the user what failed and why —
never silently retry or invent success.

## When info is missing, ASK first (do not guess)

A "project" = one website to build backlinks for. Required to add: `--project-url`
and `--niche`. If the user didn't give both, ASK before running. Optional
personalization (`--description`, `--tone`, `--keywords`, `--anchor`, `--subreddits`,
`--competitors`) improves quality — ask once, but proceed with what you have if the user declines.

## Commands

| Intent | Command |
|--------|---------|
| Add project | `add --project-url <url> --niche "<niche>" [--name ..] [--description ..] [--extra-domains quora.com,medium.com] [--tone ..] [--keywords a,b] [--subreddits saas,startups] [--competitors asana,trello] [--anchor ..] [--interval 15] [--no-seed] [--tiers 1,2]` |
| Edit personalization | `edit --project-url <url> [--niche ..] [--description ..] [--tone ..] [--keywords ..] [--subreddits ..] [--competitors ..] [--anchor ..] [--interval ..]` |
| Pause (stop scanning) | `pause --project-url <url>` |
| Resume | `resume --project-url <url>` |
| Delete (irreversible) | `delete --project-url <url> --confirm` |
| List all projects | `list` |
| One project status | `status --project-url <url>` |
| Sources + schedule | `sources --project-url <url>` |
| Scan a project now | `scan-now --project-url <url>` |
| Send cards now | `send-cards --project-url <url> [--count 5] [--gate-first]` |
| Resend unacted pending cards | `resend-pending --project-url <url> [--count 5]` |
| List pending cards (no send) | `list-pending --project-url <url> [--limit 20]` — timestamps are **IST** |
| Scan ONE site now | `scan-domain --project-url <url> --domain reddit` (aliases: `reddit`, `x`, `hn`) |
| Pin scan priority | `set-priority --project-url <url> --domain reddit --priority 90` |
| Find new sources | `find-sites --project-url <url> [--niche ..] [--max 5]` |
| Reset pipeline (keep whitelist) | `reset-opportunities [--project-url <url>] --confirm` |
| Clear site cooldowns | `reset-cooldowns [--project-url <url>]` |

## Natural-language routing (scan one site)

When the user asks to find opportunities on a **single** platform or domain, use
`scan-domain` (not `scan-now`):

- "find opportunities on Reddit for coinography" → resolve project URL, `--domain reddit`
- "scan X for https://coinography.com" → `--domain x`
- "send cards now for coinography" / "post opportunities to the group" → `send-cards --project-url https://coinography.com`
- "resend cards I haven't approved" / "show pending cards again" → `resend-pending --project-url ...`
- "list pending cards" → `list-pending --project-url ...`
- "gate and send 3 cards" → `send-cards --project-url ... --count 3 --gate-first`
- "check news.ycombinator.com for SaaS project" → `--domain news.ycombinator.com`

`scan-now` scans **all** whitelisted sites on the next daemon tick.
`scan-domain` scans **one** site immediately and returns the opportunities in the response.
`send-cards` drafts Ink content and posts Telegram cards **immediately** (ignores daemon delivery interval). Use `--gate-first` to gate SCORED leads when not enough GATED.

`resend-pending` reposts **existing** pending editorial cards from SQLite (no Ink re-draft, no duplicate DB rows). Use when cards were sent but not approved/rejected. `send-cards` is for **new** GATED harvest leads only.

## Notes

- `add` seeds the whitelist from `platforms.json` tiers 1-2 by default so the
  daemon has sites to scan immediately. Pass `--extra-domains` for additional sources
  at registration time (same as the `/onboard` extra-domains step). Pass `--no-seed` to skip seeding.
- `delete` is destructive (removes the project, its sites, and its leads).
  ALWAYS confirm with the user before passing `--confirm`.
- `scan-now` only flags sites as due; the running daemon picks them up within a
  minute. It does not itself scan.
- `scan-domain` runs synchronously: searches, inserts new leads, returns JSON list.
- `set-priority` pins a domain to scan first (0-100). Whitelist is never auto-evicted.
- `reset-opportunities --confirm` wipes opportunities, harvest_leads, and seen URLs
  but keeps projects and whitelist. Use for a fresh editorial start.
- `reset-cooldowns` clears site backoff timers so scanning resumes immediately.
- `list-pending` and `sources` show timestamps in **IST** (override with `BL_TIMEZONE`).
- **Live debug logs:** `export BL_LOG_LEVEL=verbose`, restart daemon, then `tail -f ~/.openclaw-backlink/logs/nexus_daemon.log`. Filter by stage: `grep '\[scan|'` or `grep '\[gate|'`. Default `info` keeps summary-only lines.
- **Opportunity Flywheel** (continuous discovery): daemon uses `harvester_registry` per whitelist domain — Reddit JSON, HN Algolia, RSS probe, or DDG generic search. Queries rotate via `query_planner` + bandit memory. Key env: `BL_SITES_PER_TICK=5`, `BL_SCAN_MAX_PER_SITE=20`, `BL_SCAN_QUERY_LIMIT=8`, `BL_SEARCH_QUERY_DELAY=4`, `BL_REARM_TTL_DAYS=21`, `BL_QUERY_EXPLORE_RATIO=0.2`.
- The daemon (`nexus_daemon.py`) must be running for continuous harvesting; check
  `~/.openclaw-backlink/logs/nexus_daemon.log` if nothing is being found.
