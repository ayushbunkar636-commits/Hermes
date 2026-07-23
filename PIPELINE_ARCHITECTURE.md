# OpenClaw Backlink Pipeline Architecture

> **For current agent, tool, and skill details see [AGENT_PIPELINE_REGISTRY.md](AGENT_PIPELINE_REGISTRY.md).**

## 1) System Overview

This project implements a **whitelist-based backlink system** that discovers sites, scans them for opportunities, scores and ranks candidates, generates submission-ready content, and delivers Telegram review cards to a human editor.

### Current architecture: dual-loop "Farmer"

Two independent loops share one SQLite DB (`data/backlink.db`):

```
HARVEST LOOP (24/7, pure Python — nexus_daemon.py)
  pick N DUE sites per tick → scan_tool (atomic) → insert NEW leads
    → deterministic score (score_opportunities.py)
    → quality gate (`quality_gate.py` → `bl-gate` agent; API fallback)
    → batch GATED → Ink (bl-content) drafts → Telegram cards
    → phase_resurface: stale pending cards re-sent or SENT→GATED
  per-site next_scan_due scheduling + short backoff on search blocks (not empty scans)
  ~30s air-gap sleep between ticks (BL_AIR_GAP_SECONDS)

MANAGEMENT LOOP (on-demand — bl-orchestrator / LinkNexus in Telegram)
  user message → one deterministic tool (manage_projects.py)
    → add / edit / pause / resume / delete / list / status / sources
    → scan-now / find-sites
  + editorial APPROVE / EDIT / REJECT on cards (EDITORIAL_FEEDBACK.md)
```

Cost model: the always-on harvest loop is ~free (Python + one cheap-model gate on
top-N). LLM spend is limited to content writing (Ink), the gate, and the manager
agent while a human is chatting with it.

### Legacy batch flow (retained, no longer primary)

```
LinkNexus (orchestrator)
  → Whitelist health / site finder (conditional)
  → Opportunity scanner → Score critic → Content creator
  → Telegram cards → Human editorial feedback (separate loop)
```

**Instance:** Runs as a separate OpenClaw profile (`openclaw --profile backlink`, state dir `~/.openclaw-backlink`, gateway port **19789**). Independent from the crypto news pipeline at `~/.openclaw`.

**Goal:** Build and maintain a per-project domain whitelist, find fresh backlink opportunities on those domains, score them deterministically, produce ready-to-post content with embedded project links, and route the best opportunities to Telegram for approve/edit/reject.

---

## 2) Agent Roles and Responsibilities

### 2.1 Orchestrator: LinkNexus

Defined in:

- `workspace-bl-orchestrator/IDENTITY.md`
- `workspace-bl-orchestrator/SOUL.md`

Role: Pipeline controller. Sequences worker agents, runs validation scripts, sends cards, never performs discovery or writing itself.

Key responsibilities:

- Initialize isolated run bundles.
- Spawn subagents with explicit `agentId` via `sessions_spawn` + `sessions_yield`.
- Validate every artifact before advancing.
- Retry failed steps (max 2 retries).
- Route editorial card feedback separately from pipeline steps.

### 2.2 Site Finder: Prospector

Defined in:

- `workspace-bl-site-finder/IDENTITY.md`
- `workspace-bl-site-finder/SOUL.md`

Role: Domain-level discovery for the whitelist.

Key responsibilities:

- Run tiered search via `skills/search/search.py`.
- Qualify domains that allow UGC, comments, guest posts, or listings.
- Output up to 5 new domains to `finder/new_sites.json`.
- Never invent domains from model memory.

**Conditional:** Skipped when whitelist is healthy (`WHITELIST_HEALTHY:`).

### 2.3 Opportunity Scanner: Forager

Defined in:

- `workspace-bl-opportunity-scanner/IDENTITY.md`
- `workspace-bl-opportunity-scanner/SOUL.md`

Role: URL-level opportunity discovery **inside the whitelist only**.

Key responsibilities:

- For each whitelisted domain, run `site:<domain> <niche>` searches.
- Collect deep URLs (threads, posts, questions) with verbatim excerpts.
- Output to `scan/opportunities.json`.
- Never search the open web outside the whitelist.

### 2.4 Score Critic: Arbiter

Defined in:

- `workspace-bl-score-critic/IDENTITY.md`
- `workspace-bl-score-critic/SOUL.md`

Role: Thin wrapper around deterministic scoring.

Key responsibilities:

- Execute `score_opportunities.py`.
- Write human-readable eviction summary to `score/evictions.json`.
- Yield SUCCESS without modifying scores.

Scoring formula (in script, not LLM):

- Per-opportunity score 0–100 from platform weight, recency, niche overlap, host usability, freshness bonus.
- Per-site usability score drives whitelist eviction (with hard floor of 5 sites).

### 2.5 Content Creator: Ink

Defined in:

- `workspace-bl-content/IDENTITY.md`
- `workspace-bl-content/SOUL.md`

Role: Write targeted, submission-ready responses.

Key responsibilities:

- Read ranked queue from `content_queue.json`.
- Fetch target pages for context.
- Produce one post per opportunity with embedded backlink, posting steps, and optional image.
- Write to `content/posts.json`.
- Use `generate.sh` for images (never `image_generate`).

---

## 3) Artifact Isolation — Run-Bundle Model

Every pipeline execution creates one isolated run-bundle under `/tmp/backlink-run-<RUN_ID>/`.

**Lineage rule:**

| Stage | Reads | Writes |
|-------|-------|--------|
| Init | user niche + project_url | `manifest.json`, env file |
| Prospector | current whitelist | `finder/new_sites.json` |
| merge_new_sites | finder output | SQLite whitelist |
| Forager | whitelist domains | `scan/opportunities.json` |
| dedupe | scan output | `scan/deduped.json` |
| Arbiter + score script | deduped | `score/scored.json`, `score/evictions.json` |
| sort | scored | `content_queue.json` |
| Ink | content_queue | `content/posts.json` |
| Cards | manifest + posts | Telegram messages |

**Persistence:** Long-lived state in `~/.openclaw-backlink/data/backlink.db` (projects, whitelist, harvest leads, opportunities). URLs are marked seen only on editorial approve/reject (not at scan time).

**Discovery tools (2026-06):** `search_tool.py` (ddgs primary), `read_tool.py` (Jina), `resolve_url.py`, `lead_enrich.py`, `reddit_scan.py`, `query_expander.py`, `x_filter.py`, `openweb_hunt.py`, `competitor_hunt.py`, `opportunity_hunter.py`. Project `config_json` supports `subreddits`, `target_keywords`, `competitors`, `description`.

**Farmer v2 harvest phases:** scan (whitelist `site:`) → score (niche overlap) → gate (`bl-gate` + API fallback) → openweb (every N ticks) → competitor hunt (every N ticks) → priority refresh → resurface (DB-first `resend_one_opportunity`) → draft (5 cards / 60 min). On-demand: `manage_projects.py send-cards` (new GATED), `resend-pending` (unacted pending editorial).

**Cleanup:** `cleanup_run_artifacts.sh` runs on terminal success or fatal failure. `RUN_DIR` is preserved for audit (7-day prune on next init).

---

## 4) Pipeline Execution Flow

### Step 0 — Initialize

Orchestrator runs `init_run.sh` with niche and project URL. User receives run ID confirmation.

### Step 1 — Whitelist Health

`check_whitelist_health.py` decides:

- **Empty** → seed whitelist, then finder.
- **Needs finder** → proceed to Step 2.
- **Healthy** → skip Step 2, go to Step 3.

### Step 2 — Site Finder (conditional)

Prospector discovers new domains. Orchestrator merges via `merge_new_sites.py`. Failures are non-fatal if existing whitelist has sites.

### Step 3 — Opportunity Scan

Forager scans each whitelisted domain. Dedupe against historical seen URLs. Validate scan output.

### Step 4 — Scoring

Arbiter runs deterministic scorer. Evict underperforming sites (respecting minimum whitelist size).

### Step 5 — Sort and Cap

Rank by score, emit top 30 to `content_queue.json`. Empty queue ends pipeline gracefully.

### Step 6 — Content

Ink writes posts for queued opportunities. Orchestrator validates with `validate_content.py`.

### Step 7 — Delivery

`build_and_send_card.py` sends ordered Telegram cards (fail-open per card).

### Step 8 — Cleanup

Terminal cleanup script. Orchestrator sends completion summary to user.

---

## 5) Validation Gates

| Gate | Script | Pass | Fail behavior |
|------|--------|------|---------------|
| Scan | `validate_scan.py` | `SCAN_VALID:` / `SCAN_EMPTY:` | Retry scanner (≤2), then fatal |
| Score | `validate_score.py` | `SCORE_VALID:` / `SCORE_EMPTY:` | Retry critic (≤2), then fatal |
| Content | `validate_content.py` | `CONTENT_VALID:` | Retry Ink (≤2), then fatal |
| Sort | `sort_opportunities.py` | `SORT_OK:` | `SORT_EMPTY:` → graceful end |

---

## 6) Editorial Loop (post-pipeline)

After cards are sent, human reviewers interact via Telegram:

- Callbacks: `bl_approve:`, `bl_reject:`, `bl_edit:`, etc.
- Text: APPROVE / EDIT / REJECT
- Document upload for edited markdown

Handled by `handle_card_feedback.py` per `EDITORIAL_FEEDBACK.md`. **Does not spawn subagents.**

Pending cards (`opportunities.status = pending`) may **resurface** after `BL_RESURFACE_HOURS` (default 24h) via `nexus_daemon.phase_resurface`. Approve/reject permanently marks the URL seen and suppresses re-discovery.

---

## 7) Entry and Routing

| Trigger | Handler |
|---------|---------|
| Telegram: `run backlink pipeline` + niche + URL | LinkNexus SOUL |
| Telegram: card feedback | EDITORIAL_FEEDBACK.md |
| CLI / dashboard | `openclaw --profile backlink` |

Telegram binding: `bl-orchestrator` ↔ backlink account ↔ group `-5291081154` (backlink-agent).

---

## 8) Related Documentation

- **[AGENT_PIPELINE_REGISTRY.md](AGENT_PIPELINE_REGISTRY.md)** — agents, tools, scripts, change log
- **`workspace-bl-orchestrator/SOUL.md`** — authoritative step commands
- **`workspace-bl-orchestrator/skills/search/SKILL.md`** — search provider chain
