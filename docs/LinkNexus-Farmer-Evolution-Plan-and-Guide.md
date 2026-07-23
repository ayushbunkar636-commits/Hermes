# LinkNexus Farmer Evolution
## Backlink System Upgrade — Plan & How It Works

**Document version:** June 23, 2026  
**Project:** OpenClaw Backlink (`~/.openclaw-backlink`)

---

# Part 1 — The Plan (Plain English)

## The big idea

- **Today:** Your backlink system is a "Hunter." It only runs when you manually tell it to in Telegram, does one big batch run, then stops.
- **After upgrade:** It becomes a "Farmer." It works on its own around the clock, quietly finding opportunities all day.
- **How:** Two separate "brains" share one database:
  - A **free worker** that never sleeps (Python daemon).
  - A **smart assistant** you chat with in Telegram whenever you want (orchestrator agent).

---

## Brain 1 — The free 24/7 worker (the daemon)

- Runs continuously in the background. Costs almost nothing because it is plain Python, not AI.
- Every ~60 seconds it wakes up, picks **one** website that is due for a check, looks for fresh threads, and saves them.
- It is polite: waits between checks so sites do not block us.
- If a site blocks us, it rests that site for a few hours and moves on — one bad site never stops the whole system.
- It scores every thread for free using simple rules (freshness, topic match, platform weight, etc.).
- Only the **best few** threads get passed to AI:
  - First, a **cheap AI** does a quick "is this actually good or spam?" check.
  - Then the **AI writer** drafts the reply.
- Finished cards get sent to your Telegram group for approve / edit / reject — same as today.

---

## Brain 2 — The assistant you talk to (the orchestrator)

- Lives in your Telegram group.
- **Only wakes up (and only costs money) when you message it.**
- You can ask it to do things in plain language, for example:
  - Add a new project (a new website you want backlinks for).
  - Change a project's details (niche, tone, keywords, description).
  - Pause, resume, or delete a project.
  - "Scan my project right now" instead of waiting for the schedule.
  - "Find me new source sites for this project."
  - Check status: how many opportunities found, which sites are resting, is the worker healthy.
  - Approve / reject / edit opportunity cards.

---

## How the assistant stays cheap and safe

- **Thin router:** When you ask for something, it reads only the one small instruction it needs for that task, then runs a ready-made tool. Minimal tokens.
- **Ask first:** If you did not give enough info, it asks you before doing anything.
- **Hard rules:**
  - Never changes the system on its own.
  - Never edits underlying scripts.
  - Never does anything you did not ask for.
  - If something fails, it tells you in the group clearly, with the reason.

---

## Projects (your websites)

- Each **project** = one website you want backlinks for (e.g. `memecoinist.com`).
- All personalization (niche, tone, keywords, description) is stored in the **database** so it is defined once and used everywhere.
- The worker and the AI writer both read the same project details.
- The assistant manages projects through safe, predefined tools — not by hand-editing files.

---

## What this gets you

| Goal | How it is delivered |
|------|---------------------|
| **More opportunities** | Harvesting all day instead of only when you press go |
| **Better quality** | Free rules filter the bulk; cheap AI double-checks the best ones |
| **Lower cost** | No always-on AI brain — AI only for judging top picks and writing |
| **Always working** | A block or crash on one site cannot take the whole system down |

---

## Locked design decisions

- **Scoring:** HYBRID — free math scores everything; cheap AI (`zai.glm-4.7-flash`) reads only the top-N survivors for spam/relevance.
- **Harvest trigger:** The free Python daemon calls the AI writer on demand in batches. No always-on LLM in the harvest loop.
- **Control surface:** Keep `bl-orchestrator` as an interactive Telegram agent that only runs when messaged.
- **Project storage:** SQLite `projects` table is source of truth, with columns for URL, niche, status, plus a `config_json` column for flexible personalization.
- **Orchestrator pattern:** Thin agent + fat deterministic tools + lazy skill loading + ask-then-execute + hard guardrails.

---

## Implementation checklist

1. **Database changes** — Add scheduling columns (`next_scan_due`, `failure_count`, `cooldown_until`), project config (`config_json`, `status`), and opportunity lifecycle states.
2. **scan_tool.py** — Atomic per-site scanner (one URL at a time, reports block/empty for backoff).
3. **quality_gate.py** — Cheap LLM spam/relevance check on top-N scored threads only.
4. **nexus_daemon.py** — 24/7 harvest loop with scheduling, backoff, scoring, gating, writing, and card delivery.
5. **Management tools** — `project_add`, `project_edit`, `project_pause`, `project_status`, `scan_now`, `find_sites_now`, etc.
6. **Orchestrator rework** — From pipeline sequencer to interactive manager with guardrails.
7. **Agent roster update** — Retire LLM scanner and scorer from hot path; keep Ink writer and site-finder for on-demand use.
8. **Documentation** — Update architecture docs and registry.

---

## Defaults (can be changed)

- Re-check each site every **30 minutes**.
- Rest a blocked site for **4 hours** (with exponential backoff on repeated failures).
- Cheap AI quality-check runs on the **top 10** finds each cycle.
- Daemon processes all active projects in **round-robin**.
- Manager agent can use a **cheaper model** since it mostly routes to tools.

---

# Part 2 — How the System Works After Implementation

## The 10,000-foot view: two loops running side by side

Two things are alive at once. They never wait on each other. They share one database.

**Diagram — Two brains, one database:**

```
flowchart LR
    subgraph you [You]
        TG[Telegram group]
    end
    subgraph b1 [Brain 1: Free worker - always on]
        DAEMON[nexus daemon loop]
    end
    subgraph b2 [Brain 2: Assistant - wakes only when messaged]
        ORC[orchestrator agent]
    end
    DB[(shared database)]
    TG <-->|chat commands| ORC
    ORC <-->|read/write projects| DB
    DAEMON <-->|read sites, save finds| DB
    DAEMON -->|opportunity cards| TG
    TG -->|approve / edit / reject| ORC
```

**In plain English:**

- **Brain 1 (worker)** is busy 24/7 finding opportunities. Costs almost nothing.
- **Brain 2 (assistant)** sleeps until you message it. Costs money only during that chat.
- The **database** is the shared notebook both write into.

---

## Step 1 — You set up a project (one-time, via Telegram)

**Diagram — Adding a project:**

```
sequenceDiagram
    participant You
    participant Assistant as Orchestrator
    participant Tool as project_add tool
    participant DB as Database
    You->>Assistant: Add a new project: mysite.com, niche = SaaS marketing
    Assistant->>Assistant: Reads ONLY the add-project instruction
    alt Missing info
        Assistant->>You: What tone and target keywords?
        You->>Assistant: provides details
    end
    Assistant->>Tool: run with the details
    Tool->>DB: save project + personalization
    Assistant->>You: Project added. Worker will start finding opportunities.
```

**What happens:**

1. You message the Telegram group in plain language.
2. The assistant loads only the "add project" skill — not everything else.
3. If info is missing, it asks you.
4. It runs a safe predefined tool that writes to the database.
5. The worker picks up the new project on its next cycle.

---

## Step 2 — The worker harvests all day on its own

**Diagram — The harvest heartbeat (repeats forever):**

```
flowchart TD
    START[Wake up every ~60s] --> PICK{Any site due for a check?}
    PICK -->|No| SLEEP[Sleep, try again later]
    PICK -->|Yes| ONE[Pick ONE due site]
    ONE --> SCAN[Look for fresh threads on it]
    SCAN --> OK{Did it work?}
    OK -->|Blocked or empty| BACKOFF[Rest this site a few hours, move on]
    OK -->|Success| SAVE[Save new threads as NEW]
    SAVE --> RESCHED[Schedule this site again in ~30 min]
    RESCHED --> SCORE[Score all NEW threads with free rules]
    SCORE --> TOPN[Take only the best few]
    TOPN --> GATE[Cheap AI checks: spam or genuinely relevant?]
    GATE --> WRITE[AI writer drafts replies for the winners]
    WRITE --> CARD[Send cards to your Telegram]
    BACKOFF --> SLEEP
    CARD --> SLEEP
    SLEEP --> START
```

**What happens each cycle:**

1. Worker wakes up (~every 60 seconds).
2. Finds one site where `next_scan_due <= now` and it is not in cooldown.
3. Scans that one site for fresh threads (< 7 days old).
4. **Success:** Saves threads, reschedules site for +30 min, scores them, gates top-N, writes drafts, sends cards.
5. **Blocked/empty:** Increments failure count, puts site in cooldown (+4h with backoff), moves on.
6. Sleeps and repeats.

---

## Step 3 — You review the cards (approve / edit / reject)

**Diagram — Editorial loop:**

```
sequenceDiagram
    participant Worker
    participant You
    participant Assistant as Orchestrator
    participant DB as Database
    Worker->>You: Opportunity card (thread + draft reply + link)
    You->>Assistant: tap Approve / Edit / Reject
    Assistant->>DB: record your decision
    Note over DB: Approvals teach the system which sites are worth more
```

**What happens:**

- Same review experience as today.
- Your approvals and rejections feed back into scoring over time.
- Sites that produce good results get favored; weak sites get rested or evicted.

---

## Step 4 — Anything else, just ask the assistant

At any time you can message the group:

| You say | What happens |
|---------|--------------|
| "Scan mysite.com right now" | Project bumped to front of worker queue |
| "How are things going?" | Status report: counts, cooldowns, worker health |
| "Find new source sites for mysite.com" | On-demand domain discovery |
| "Pause the crypto project" | Project paused safely in database |
| "Change niche for project X" | Updates `config_json`, applies everywhere |

---

## Why this is cheap and reliable

**Diagram — What costs money vs what is free:**

```
flowchart LR
    subgraph free [Free / near-free]
        A[Worker loop]
        B[Searching sites]
        C[Rule-based scoring]
        D[Assistant idle]
    end
    subgraph paid [Pay only here]
        E[Cheap AI spam-check on top few]
        F[AI writing the drafts]
        G[Assistant while you chat]
    end
    free --> RESULT[Many quality opportunities, low cost, always running]
    paid --> RESULT
```

---

## Technical architecture (for reference)

**Diagram — Full system architecture:**

```
flowchart TD
    subgraph farmer [Harvest Loop - 24/7 free Python daemon]
        D[nexus_daemon.py] -->|pick 1 site due| ST[scan_tool.scan_single_url]
        ST -->|insert NEW threads| DB[(backlink.db)]
        D -->|score NEW| SCORE[score_opportunities.py]
        SCORE -->|top-N only| GATE[quality_gate.py - cheap LLM]
        GATE -->|batch of winners| INK[bl-content Ink - AI on demand]
        INK -->|cards| CARD[build_and_send_card.py]
    end
    subgraph manager [Management Loop - on-demand only]
        TG[Telegram group] <-->|chat| ORC[bl-orchestrator manager]
        ORC -->|reads 1 skill, runs 1 tool| TOOLS[project_add / edit / pause / status / scan_now / find_sites]
        TOOLS --> DB
    end
    DB --- D
    DB --- ORC
```

---

## Opportunity lifecycle (database states)

Each thread moves through these states:

```
NEW  →  SCORED  →  GATED  →  DRAFTED  →  SENT  →  APPROVED / REJECTED
```

| State | Meaning |
|-------|---------|
| NEW | Just found by the worker |
| SCORED | Free rules applied a 0–100 score |
| GATED | Cheap AI passed it (not spam, relevant) |
| DRAFTED | AI writer created the reply |
| SENT | Telegram card delivered to you |
| APPROVED / REJECTED | Your editorial decision |

---

## Agent roster after upgrade

| Agent | Role | When it runs | Cost |
|-------|------|--------------|------|
| `nexus_daemon.py` | 24/7 harvest worker | Always (Python, not AI) | Free |
| `bl-orchestrator` | Interactive manager | When you message Telegram | Low (only while chatting) |
| `bl-content` (Ink) | Writes reply drafts | On demand, batched | Medium (quality writing) |
| `bl-site-finder` | Finds new source sites | On demand / weekly | Low–medium |
| ~~bl-opportunity-scanner~~ | Retired from hot path | — | — |
| ~~bl-score-critic~~ | Retired from hot path | — | — |

---

## Key files (after implementation)

| File | Purpose |
|------|---------|
| `skills/pipeline/nexus_daemon.py` | 24/7 harvest loop |
| `skills/pipeline/scan_tool.py` | Atomic per-site scanner |
| `skills/pipeline/quality_gate.py` | Cheap LLM relevance/spam gate |
| `skills/pipeline/project_add.py` | Add project tool |
| `skills/pipeline/project_edit.py` | Edit project tool |
| `skills/pipeline/scan_now.py` | Trigger immediate scan |
| `skills/search/search.py` | Tiered search (DDG → SearXNG) |
| `skills/search/discover.py` | Batch discovery helper |
| `data/backlink.db` | Shared SQLite database |

---

*End of document*
