#!/usr/bin/env python3
"""whitelist_db.py — SQLite schema and helpers for the per-project whitelist system.

New tables (all additive; existing opportunities/feedback_events tables untouched):
  projects             — one row per project_url
  whitelist_sites      — per-project domain whitelist with scoring + status
  site_score_history   — append-only usability score snapshots (drives eviction)
  seen_opportunities   — dedup memory: url_key × project_id
  pipeline_runs        — run manifest index

DB path is shared with backlink_db.py: ~/.openclaw-backlink/data/backlink.db
WAL mode is enabled on every connection open so reads never block writes.
"""
from __future__ import annotations

import json
import os
import config
import psycopg2
import psycopg2.extras
import os
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class OnboardSession:
    id: int
    chat_id: str
    user_id: str
    step: str
    answers_json: str
    prompt_message_id: int | None

DEFAULT_DB_PATH = os.path.expanduser("~/.openclaw-backlink/data/backlink.db")

MIN_WHITELIST = 5  # Hard floor: never evict below this many active sites per project

_NEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id          INTEGER PRIMARY KEY ,
  project_url TEXT    NOT NULL UNIQUE,
  niche       TEXT,
  name        TEXT,
  status      TEXT    NOT NULL DEFAULT 'active',  -- active | paused
  config_json TEXT,                               -- flexible personalization blob
  scan_interval_minutes INTEGER NOT NULL DEFAULT 30,
  telegram_group_id   TEXT,                       -- per-project Telegram supergroup
  telegram_group_name TEXT,
  card_prefix         TEXT,                       -- optional card label prefix
  domain_authority    INTEGER,
  domain_rating       INTEGER,
  trust_flow          INTEGER,
  citation_flow       INTEGER,
  organic_keywords    INTEGER,
  organic_traffic     INTEGER,
  referring_domains   INTEGER,
  indexed_pages       INTEGER,
  created_at  TEXT    DEFAULT (timezone('utc', now()))
);

CREATE TABLE IF NOT EXISTS whitelist_sites (
  id                    INTEGER PRIMARY KEY ,
  project_id            INTEGER NOT NULL REFERENCES projects(id),
  domain                TEXT    NOT NULL,
  status                TEXT    NOT NULL DEFAULT 'active',  -- active | benched | evicted | cooldown
  added_at              TEXT    DEFAULT (timezone('utc', now())),
  added_by              TEXT    NOT NULL DEFAULT 'manual',  -- seed | finder | manual
  last_scanned_at       TEXT,
  current_usability_score REAL  DEFAULT NULL,
  next_scan_due         TEXT,                               -- Farmer: when this site may be scanned again
  failure_count         INTEGER NOT NULL DEFAULT 0,         -- consecutive block/empty count
  cooldown_until        TEXT,                               -- if set and in future, site is resting
  scan_priority         INTEGER NOT NULL DEFAULT 50,       -- higher = scan first (never evicts)
  domain_authority      INTEGER,
  domain_rating         INTEGER,
  trust_flow            INTEGER,
  citation_flow         INTEGER,
  organic_keywords      INTEGER,
  organic_traffic       INTEGER,
  referring_domains     INTEGER,
  UNIQUE(project_id, domain)
);
CREATE INDEX IF NOT EXISTS idx_wl_project_status ON whitelist_sites(project_id, status);

CREATE TABLE IF NOT EXISTS harvest_leads (
  id                   INTEGER PRIMARY KEY ,
  project_id           INTEGER NOT NULL REFERENCES projects(id),
  whitelist_site_id    INTEGER REFERENCES whitelist_sites(id),
  url                  TEXT    NOT NULL,
  url_key              TEXT    NOT NULL,
  domain               TEXT,
  type                 TEXT,
  target_title         TEXT,
  target_excerpt       TEXT,
  opportunity_context  TEXT,
  opportunity_freshness TEXT,
  posting_action       TEXT,
  platform             TEXT,
  platform_weight      REAL,
  credibility_tier     INTEGER,
  relevance_score      REAL,
  recency_score        REAL,
  score_100            REAL,
  gate_score           REAL,
  gate_reason          TEXT,
  status               TEXT NOT NULL DEFAULT 'NEW',  -- NEW | SCORED | GATED | REJECTED | DRAFTED | SENT | FAILED
  run_id               TEXT,
  raw_json             TEXT,
  url_rating           INTEGER,
  page_authority       INTEGER,
  estimated_traffic    INTEGER,
  page_language        TEXT,
  country              TEXT,
  page_age_days        INTEGER,
  is_dofollow          BOOLEAN,
  is_sponsored         BOOLEAN,
  is_ugc               BOOLEAN,
  is_redirect          BOOLEAN,
  has_canonical        BOOLEAN,
  anchor_text          TEXT,
  link_position        TEXT,
  outbound_link_count  INTEGER,
  discussion_intent    TEXT,
  question_type        TEXT,
  buying_intent        TEXT,
  engagement_score     REAL,
  comment_count        INTEGER,
  created_at           TEXT DEFAULT (timezone('utc', now())),
  updated_at           TEXT DEFAULT (timezone('utc', now())),
  UNIQUE(project_id, url_key)
);
CREATE INDEX IF NOT EXISTS idx_lead_status ON harvest_leads(status, score_100);
CREATE INDEX IF NOT EXISTS idx_lead_project ON harvest_leads(project_id, status);

CREATE TABLE IF NOT EXISTS site_score_history (
  id                   INTEGER PRIMARY KEY ,
  whitelist_site_id    INTEGER NOT NULL REFERENCES whitelist_sites(id),
  score_0_100          REAL    NOT NULL,
  approvals            INTEGER NOT NULL DEFAULT 0,
  rejects              INTEGER NOT NULL DEFAULT 0,
  opportunities_emitted INTEGER NOT NULL DEFAULT 0,
  recorded_at          TEXT    DEFAULT (timezone('utc', now()))
);
CREATE INDEX IF NOT EXISTS idx_ssh_site ON site_score_history(whitelist_site_id, recorded_at);

CREATE TABLE IF NOT EXISTS seen_opportunities (
  id           INTEGER PRIMARY KEY ,
  project_id   INTEGER NOT NULL REFERENCES projects(id),
  url_key      TEXT    NOT NULL,
  first_seen_at TEXT   DEFAULT (timezone('utc', now())),
  UNIQUE(project_id, url_key)
);
CREATE INDEX IF NOT EXISTS idx_seen_project ON seen_opportunities(project_id);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  id           INTEGER PRIMARY KEY ,
  run_id       TEXT    NOT NULL UNIQUE,
  project_id   INTEGER REFERENCES projects(id),
  started_at   TEXT    DEFAULT (timezone('utc', now())),
  finished_at  TEXT,
  status       TEXT    DEFAULT 'running',  -- running | success | failed
  summary_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_pr_project ON pipeline_runs(project_id, started_at);

CREATE TABLE IF NOT EXISTS harvest_cursors (
  whitelist_site_id INTEGER PRIMARY KEY REFERENCES whitelist_sites(id),
  state_json        TEXT NOT NULL DEFAULT '{}',
  updated_at        TEXT DEFAULT (timezone('utc', now()))
);

CREATE TABLE IF NOT EXISTS query_stats (
  id           INTEGER PRIMARY KEY ,
  project_id   INTEGER NOT NULL REFERENCES projects(id),
  domain       TEXT NOT NULL,
  template_id  TEXT NOT NULL,
  runs         INTEGER NOT NULL DEFAULT 0,
  new_leads    INTEGER NOT NULL DEFAULT 0,
  last_used    TEXT,
  UNIQUE(project_id, domain, template_id)
);
CREATE INDEX IF NOT EXISTS idx_query_stats_yield ON query_stats(project_id, domain, new_leads);

CREATE TABLE IF NOT EXISTS vocab_terms (
  id          INTEGER PRIMARY KEY ,
  project_id  INTEGER NOT NULL REFERENCES projects(id),
  term        TEXT NOT NULL,
  score       REAL NOT NULL DEFAULT 0,
  source      TEXT,
  added_at    TEXT DEFAULT (timezone('utc', now())),
  UNIQUE(project_id, term)
);
CREATE INDEX IF NOT EXISTS idx_vocab_project ON vocab_terms(project_id, score DESC);

CREATE TABLE IF NOT EXISTS domain_candidates (
  id           INTEGER PRIMARY KEY ,
  project_id   INTEGER NOT NULL REFERENCES projects(id),
  domain       TEXT NOT NULL,
  source_url   TEXT,
  status       TEXT NOT NULL DEFAULT 'pending',
  created_at   TEXT DEFAULT (timezone('utc', now())),
  UNIQUE(project_id, domain)
);

CREATE TABLE IF NOT EXISTS onboard_sessions (
  id INTEGER PRIMARY KEY ,
  chat_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  step TEXT NOT NULL,
  answers_json TEXT NOT NULL DEFAULT '{}',
  prompt_message_id INTEGER,
  created_at TEXT DEFAULT (timezone('utc', now())),
  updated_at TEXT DEFAULT (timezone('utc', now())),
  UNIQUE(chat_id, user_id)
);
"""


# Additive column migrations for databases created before these columns existed.
# Each runs ALTER TABLE ... ADD COLUMN only when the column is missing, so
# existing rows migrate in place without data loss.
_COLUMN_MIGRATIONS: dict[str, dict[str, str]] = {
    "projects": {
        "status": "ALTER TABLE projects ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "config_json": "ALTER TABLE projects ADD COLUMN config_json TEXT",
        "scan_interval_minutes": "ALTER TABLE projects ADD COLUMN scan_interval_minutes INTEGER NOT NULL DEFAULT 30",
        "telegram_group_id": "ALTER TABLE projects ADD COLUMN telegram_group_id TEXT",
        "telegram_group_name": "ALTER TABLE projects ADD COLUMN telegram_group_name TEXT",
        "card_prefix": "ALTER TABLE projects ADD COLUMN card_prefix TEXT",
    },
    "harvest_leads": {
        "draft_attempts": "ALTER TABLE harvest_leads ADD COLUMN draft_attempts INTEGER NOT NULL DEFAULT 0",
    },
    "whitelist_sites": {
        "next_scan_due": "ALTER TABLE whitelist_sites ADD COLUMN next_scan_due TEXT",
        "failure_count": "ALTER TABLE whitelist_sites ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0",
        "cooldown_until": "ALTER TABLE whitelist_sites ADD COLUMN cooldown_until TEXT",
        "scan_priority": "ALTER TABLE whitelist_sites ADD COLUMN scan_priority INTEGER NOT NULL DEFAULT 50",
    },
    "seen_opportunities": {
        "last_activity_at": "ALTER TABLE seen_opportunities ADD COLUMN last_activity_at TEXT",
        "rearm_after": "ALTER TABLE seen_opportunities ADD COLUMN rearm_after TEXT",
        "editorial_locked": "ALTER TABLE seen_opportunities ADD COLUMN editorial_locked INTEGER NOT NULL DEFAULT 0",
    },
}


def _connect(db_path: str = None):
    return config.get_db_connection()


def _run_column_migrations(conn: psycopg2.extensions.connection) -> None:
    for table, columns in _COLUMN_MIGRATIONS.items():
        existing = {row["column_name"] for row in conn.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'")}
        if not existing:
            continue  # table not created yet; executescript will handle it
        for col, ddl in columns.items():
            if col not in existing:
                conn.execute(ddl)


# Indexes that reference columns added by migration must be created AFTER the
# column migrations run, so pre-existing tables get the column first.
_POST_MIGRATION_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_wl_due ON whitelist_sites(status, next_scan_due)",
)


def init_whitelist_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create new tables if missing and apply additive column migrations. Idempotent."""
    with _connect(db_path) as conn:
        conn.executescript(_NEW_SCHEMA)
        _run_column_migrations(conn)
        for ddl in _POST_MIGRATION_INDEXES:
            conn.execute(ddl)
        conn.commit()


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------

def upsert_project(project_url: str, niche: str, name: str = "", db_path: str = DEFAULT_DB_PATH) -> int:
    """Insert or ignore project row. Returns project_id."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO projects (project_url, niche, name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (project_url.strip(), niche.strip(), name.strip()),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM projects WHERE project_url=%s", (project_url.strip(),)).fetchone()
    return int(row["id"])


def get_project_id(project_url: str, db_path: str = DEFAULT_DB_PATH) -> int | None:
    """Return project_id or None if not registered yet."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT id FROM projects WHERE project_url=%s", (project_url.strip(),)).fetchone()
    return int(row["id"]) if row else None


# ---------------------------------------------------------------------------
# whitelist_sites
# ---------------------------------------------------------------------------

def upsert_whitelist_site(
    project_id: int,
    domain: str,
    added_by: str = "manual",
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Insert or leave-intact a whitelist site. Returns whitelist_site_id."""
    init_whitelist_db(db_path)
    domain = domain.lower().strip().lstrip("www.")
    with _connect(db_path) as conn:
        # New sites are immediately due for a scan (next_scan_due = now).
        conn.execute(
            """
            INSERT INTO whitelist_sites (project_id, domain, added_by, status, next_scan_due)
            VALUES (%s, %s, %s, 'active', timezone('utc', now()))
            ON CONFLICT(project_id, domain) DO NOTHING
            """,
            (project_id, domain, added_by),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM whitelist_sites WHERE project_id=%s AND domain=%s",
            (project_id, domain),
        ).fetchone()
    return int(row["id"])


def get_active_whitelist(project_id: int, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Return list of active whitelist site dicts for a project."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM whitelist_sites WHERE project_id=%s AND status = 'active' ORDER BY added_at",
            (project_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_active_sites(project_id: int, db_path: str = DEFAULT_DB_PATH) -> int:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM whitelist_sites WHERE project_id=%s AND status = 'active'",
            (project_id,),
        ).fetchone()
    return int(row["n"])


def set_site_status(whitelist_site_id: int, status: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Update status of a whitelist site (active | benched | evicted)."""
    assert status in ("active", "benched", "evicted"), f"Invalid status: {status}"
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("UPDATE whitelist_sites SET status=%s WHERE id=%s", (status, whitelist_site_id))
        conn.commit()


def update_site_usability_score(whitelist_site_id: int, score: float, db_path: str = DEFAULT_DB_PATH) -> None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE whitelist_sites SET current_usability_score=%s WHERE id=%s",
            (score, whitelist_site_id),
        )
        conn.commit()


def touch_last_scanned(whitelist_site_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE whitelist_sites SET last_scanned_at = timezone('utc', now()) WHERE id=%s",
            (whitelist_site_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# site_score_history
# ---------------------------------------------------------------------------

def append_score_history(
    whitelist_site_id: int,
    score_0_100: float,
    approvals: int = 0,
    rejects: int = 0,
    opportunities_emitted: int = 0,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO site_score_history
              (whitelist_site_id, score_0_100, approvals, rejects, opportunities_emitted)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (whitelist_site_id, score_0_100, approvals, rejects, opportunities_emitted),
        )
        conn.commit()


def get_recent_scores(
    whitelist_site_id: int,
    limit: int = 10,
    days: int = 30,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict]:
    """Return up to `limit` most-recent score rows within last `days` days."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM site_score_history
            WHERE whitelist_site_id=%s
              AND recorded_at >= NOW() AT TIME ZONE 'UTC' + CAST(%s || ' days' AS INTERVAL)
            ORDER BY recorded_at DESC
            LIMIT %s
            """,
            (whitelist_site_id, f"-{days}", limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# seen_opportunities
# ---------------------------------------------------------------------------

def is_seen(project_id: int, url_key: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_opportunities WHERE project_id=%s AND url_key=%s",
            (project_id, url_key),
        ).fetchone()
    return row is not None


def mark_seen_batch(project_id: int, url_keys: list[str], db_path: str = DEFAULT_DB_PATH) -> None:
    """Record a batch of url_keys as seen. Ignores duplicates."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO seen_opportunities (project_id, url_key) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            [(project_id, k) for k in url_keys],
        )
        conn.commit()


def mark_seen_editorial(project_id: int, url_key: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Mark URL seen after editorial approve/reject — never re-arm."""
    init_whitelist_db(db_path)
    key = str(url_key or "").lower().rstrip("/")
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO seen_opportunities (project_id, url_key, editorial_locked, last_activity_at)
            VALUES (%s, %s, 1, timezone('utc', now()))
            ON CONFLICT(project_id, url_key) DO UPDATE SET
              editorial_locked = 1,
              last_activity_at = timezone('utc', now())
            """,
            (project_id, key),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# pipeline_runs
# ---------------------------------------------------------------------------

def register_run(run_id: str, project_id: int | None = None, db_path: str = DEFAULT_DB_PATH) -> None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, project_id, status) VALUES (%s, %s, 'running') ON CONFLICT DO NOTHING",
            (run_id, project_id),
        )
        conn.commit()


def finish_run(
    run_id: str,
    status: str = "success",
    summary: dict | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    init_whitelist_db(db_path)
    summary_json = json.dumps(summary, ensure_ascii=False) if summary else None
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE pipeline_runs SET status=%s, finished_at = timezone('utc', now()), summary_json = %s WHERE run_id=%s",
            (status, summary_json, run_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# projects — Farmer management (used by orchestrator tools + daemon)
# ---------------------------------------------------------------------------

def add_or_update_project(
    project_url: str,
    niche: str,
    name: str = "",
    config: dict | None = None,
    scan_interval_minutes: int = 15,
    status: str = "active",
    telegram_group_id: str | None = None,
    telegram_group_name: str | None = None,
    card_prefix: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Create a project or update its metadata. Returns project_id.

    config is stored as a JSON blob (single source of truth for personalization:
    tone, target_keywords, anchor_text, description, etc.).
    """
    init_whitelist_db(db_path)
    pid = upsert_project(project_url, niche, name, db_path=db_path)
    config_json = json.dumps(config, ensure_ascii=False) if config is not None else None
    with _connect(db_path) as conn:
        sets = ["niche = %s", "status = %s", "scan_interval_minutes = %s"]
        params: list[Any] = [niche.strip(), status, int(scan_interval_minutes)]
        if name.strip():
            sets.append("name = %s")
            params.append(name.strip())
        if config_json is not None:
            sets.append("config_json = %s")
            params.append(config_json)
        if telegram_group_id is not None:
            sets.append("telegram_group_id = %s")
            params.append(str(telegram_group_id).strip() or None)
        if telegram_group_name is not None:
            sets.append("telegram_group_name = %s")
            params.append(str(telegram_group_name).strip() or None)
        if card_prefix is not None:
            sets.append("card_prefix = %s")
            params.append(str(card_prefix).strip() or None)
        params.append(pid)
        conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=%s", params)
        conn.commit()
    return pid


def update_project_config(project_url: str, patch: dict, db_path: str = DEFAULT_DB_PATH) -> dict:
    """Shallow-merge patch into the project's config_json. Returns the new config."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, config_json FROM projects WHERE project_url=%s", (project_url.strip(),)
        ).fetchone()
        if not row:
            raise ValueError(f"project not found: {project_url}")
        current = {}
        if row["config_json"]:
            try:
                current = json.loads(row["config_json"])
            except json.JSONDecodeError:
                current = {}
        current.update(patch or {})
        conn.execute(
            "UPDATE projects SET config_json=%s WHERE id=%s",
            (json.dumps(current, ensure_ascii=False), row["id"]),
        )
        conn.commit()
    return current


def _normalize_chat_id(chat_id: str) -> str:
    """Normalize Telegram chat id for comparison (strip whitespace, keep sign)."""
    return str(chat_id or "").strip()


def set_project_group(
    project_url: str,
    group_id: str,
    group_name: str = "",
    *,
    card_prefix: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Persist per-project Telegram group routing (egress + reverse lookup)."""
    init_whitelist_db(db_path)
    gid = _normalize_chat_id(group_id)
    if not gid:
        raise ValueError("group_id is required")
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE project_url=%s", (project_url.strip(),)
        ).fetchone()
        if not row:
            raise ValueError(f"project not found: {project_url}")
        dup = conn.execute(
            "SELECT project_url FROM projects WHERE telegram_group_id=%s AND project_url != %s",
            (gid, project_url.strip()),
        ).fetchone()
        if dup:
            raise ValueError(
                f"group_id {gid} already bound to project {dup['project_url']}"
            )
        sets = ["telegram_group_id = %s", "telegram_group_name = %s"]
        params: list[Any] = [gid, (group_name or "").strip() or None]
        if card_prefix is not None:
            sets.append("card_prefix = %s")
            params.append(str(card_prefix).strip() or None)
        params.append(project_url.strip())
        conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE project_url=%s", params)
        conn.commit()


def resolve_project_for_group(group_id: str, db_path: str = DEFAULT_DB_PATH) -> str | None:
    """Return project_url bound to a Telegram group chat id, if any."""
    init_whitelist_db(db_path)
    gid = _normalize_chat_id(group_id)
    if not gid:
        return None
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT project_url, telegram_group_id FROM projects WHERE telegram_group_id IS NOT NULL"
        ).fetchall()
    for row in rows:
        if _normalize_chat_id(row["telegram_group_id"]) == gid:
            return str(row["project_url"])
    return None


def resolve_chat_id_for_project(
    project_url: str,
    *,
    fallback: str = "",
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """Return telegram_group_id for a project, or fallback if unset."""
    proj = get_project(project_url, db_path=db_path)
    if proj:
        gid = _normalize_chat_id(proj.get("telegram_group_id") or "")
        if gid:
            return gid
    return _normalize_chat_id(fallback)


def set_project_status(project_url: str, status: str, db_path: str = DEFAULT_DB_PATH) -> None:
    assert status in ("active", "paused"), f"invalid project status: {status}"
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE projects SET status=%s WHERE project_url=%s", (status, project_url.strip())
        )
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"project not found: {project_url}")


def get_project(project_url: str, db_path: str = DEFAULT_DB_PATH) -> dict | None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM projects WHERE project_url=%s", (project_url.strip(),)).fetchone()
    return dict(row) if row else None


def list_projects(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def get_active_projects(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM projects WHERE status = 'active' ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def delete_project(project_url: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Remove a project and all of its sites/leads. Irreversible."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT id FROM projects WHERE project_url=%s", (project_url.strip(),)).fetchone()
        if not row:
            raise ValueError(f"project not found: {project_url}")
        pid = row["id"]
        conn.execute("DELETE FROM harvest_leads WHERE project_id=%s", (pid,))
        conn.execute("DELETE FROM seen_opportunities WHERE project_id=%s", (pid,))
        
        # New additions for PostgreSQL dependencies
        conn.execute("DELETE FROM project_sitemaps WHERE project_id=%s", (pid,))
        conn.execute("DELETE FROM project_competitors WHERE project_id=%s", (pid,))
        conn.execute("DELETE FROM project_vocab WHERE project_id=%s", (pid,))
        conn.execute("DELETE FROM domain_scores WHERE project_id=%s", (pid,))
        conn.execute("DELETE FROM leads WHERE project_id=%s", (pid,))
        conn.execute("DELETE FROM pipeline_runs WHERE project_id=%s", (pid,))
        
        # Foreign keys cascading through whitelist_sites
        conn.execute(
            "DELETE FROM harvest_cursors WHERE whitelist_site_id IN "
            "(SELECT id FROM whitelist_sites WHERE project_id=%s)",
            (pid,),
        )
        conn.execute(
            "DELETE FROM harvest_leads WHERE whitelist_site_id IN "
            "(SELECT id FROM whitelist_sites WHERE project_id=%s)",
            (pid,),
        )
        
        # Foreign keys cascading through opportunities
        conn.execute(
            "DELETE FROM feedback_events WHERE opportunity_id IN "
            "(SELECT id FROM opportunities WHERE project_id=%s OR project_url=%s)",
            (pid, project_url),
        )
        conn.execute("DELETE FROM opportunities WHERE project_id=%s OR project_url=%s", (pid, project_url))
        
        conn.execute(
            "DELETE FROM site_score_history WHERE whitelist_site_id IN "
            "(SELECT id FROM whitelist_sites WHERE project_id=%s)",
            (pid,),
        )
        conn.execute("DELETE FROM whitelist_sites WHERE project_id=%s", (pid,))
        conn.execute("DELETE FROM projects WHERE id=%s", (pid,))
        conn.commit()


# ---------------------------------------------------------------------------
# Farmer scheduling — per-site next_scan_due / backoff
# ---------------------------------------------------------------------------

def get_due_sites(limit: int = 1, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Return active sites (in active projects) that are due for a scan now.

    A site is due when next_scan_due is NULL or <= now, and it is not in an
    active cooldown window. Ordered oldest-due first for fair round-robin.
    """
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT w.*, p.niche AS project_niche, p.project_url AS project_url,
                   p.name AS project_name, p.config_json AS project_config_json,
                   p.scan_interval_minutes AS scan_interval_minutes
            FROM whitelist_sites w
            JOIN projects p ON p.id = w.project_id
            WHERE p.status = 'active'
              AND w.status IN ('active', 'cooldown')
              AND (w.next_scan_due IS NULL OR w.next_scan_due <= timezone('utc', now()))
              AND (w.cooldown_until IS NULL OR w.cooldown_until <= timezone('utc', now()))
            ORDER BY COALESCE(w.scan_priority, 50) DESC,
                     (w.next_scan_due IS NULL) DESC, w.next_scan_due ASC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_site_scanned_success(
    whitelist_site_id: int,
    interval_minutes: int = 30,
    *,
    leads_inserted: int = 0,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Record a successful scan: reset failures, reschedule +interval, clear cooldown.

    Adaptive interval: high yield scans sooner, zero-yield scans later (within bounds).
    """
    if leads_inserted >= 3:
        interval_minutes = max(5, interval_minutes // 2)
    elif leads_inserted == 0:
        interval_minutes = min(int(interval_minutes * 1.5), 180)
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE whitelist_sites
            SET last_scanned_at = timezone('utc', now()),
                next_scan_due   = NOW() AT TIME ZONE 'UTC' + CAST(%s || ' minutes' AS INTERVAL),
                failure_count   = 0,
                cooldown_until  = NULL,
                status          = CASE WHEN status = 'cooldown' THEN 'active' ELSE status END
            WHERE id=%s
            """,
            (f"+{int(interval_minutes)}", whitelist_site_id),
        )
        conn.commit()


def mark_site_blocked(
    whitelist_site_id: int, base_backoff_hours: float = 4.0, max_backoff_hours: float = 48.0,
    db_path: str = DEFAULT_DB_PATH,
) -> float:
    """Record a block/empty failure: increment failure_count and apply exponential
    backoff cooldown (base * 2^(failures-1), capped). Returns the backoff hours used."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT failure_count FROM whitelist_sites WHERE id=%s", (whitelist_site_id,)
        ).fetchone()
        failures = (int(row["failure_count"]) if row and row["failure_count"] is not None else 0) + 1
        backoff = min(base_backoff_hours * (2 ** (failures - 1)), max_backoff_hours)
        minutes = int(backoff * 60)
        conn.execute(
            """
            UPDATE whitelist_sites
            SET failure_count=%s,
                last_scanned_at = timezone('utc', now()),
                cooldown_until = NOW() AT TIME ZONE 'UTC' + CAST(%s || ' minutes' AS INTERVAL),
                next_scan_due  = NOW() AT TIME ZONE 'UTC' + CAST(%s || ' minutes' AS INTERVAL),
                status         = 'cooldown'
            WHERE id=%s
            """,
            (failures, f"+{minutes}", f"+{minutes}", whitelist_site_id),
        )
        conn.commit()
    return backoff


def set_project_sites_due_now(project_id: int, db_path: str = DEFAULT_DB_PATH) -> int:
    """Force every active site in a project to be due immediately (for 'scan now')."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE whitelist_sites
            SET next_scan_due = timezone('utc', now()), cooldown_until = NULL,
                status = CASE WHEN status = 'cooldown' THEN 'active' ELSE status END
            WHERE project_id=%s AND status IN ('active', 'cooldown')
            """,
            (project_id,),
        )
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# harvest_leads — the NEW -> SCORED -> GATED -> DRAFTED -> SENT lifecycle
# ---------------------------------------------------------------------------

def insert_leads(
    project_id: int, whitelist_site_id: int | None, leads: list[dict], db_path: str = DEFAULT_DB_PATH
) -> int:
    """Insert NEW leads, skipping any already seen (url_key dedup). Returns count inserted."""
    init_whitelist_db(db_path)
    inserted = 0
    with _connect(db_path) as conn:
        for lead in leads:
            url = str(lead.get("url") or "").strip()
            if not url:
                continue
            key = str(lead.get("url_key") or url).lower().rstrip("/")
            try:
                cur = conn.execute(
                    """
                    INSERT INTO harvest_leads (
                      project_id, whitelist_site_id, url, url_key, domain, type,
                      target_title, target_excerpt, opportunity_context, opportunity_freshness,
                      posting_action, platform, platform_weight, credibility_tier,
                      relevance_score, recency_score, status, raw_json,
                      page_language, has_canonical, is_dofollow, is_ugc, is_sponsored, outbound_link_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'NEW', %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(project_id, url_key) DO NOTHING
                    """,
                    (
                        project_id, whitelist_site_id, url, key,
                        lead.get("domain"), lead.get("type"),
                        lead.get("target_title"), lead.get("target_excerpt"),
                        lead.get("opportunity_context"), lead.get("opportunity_freshness"),
                        lead.get("posting_action"), lead.get("platform"),
                        lead.get("platform_weight"), lead.get("credibility_tier"),
                        lead.get("relevance_score"), lead.get("recency_score"),
                        json.dumps(lead, ensure_ascii=False),
                        lead.get("page_language"), lead.get("has_canonical"),
                        lead.get("is_dofollow"), lead.get("is_ugc"),
                        lead.get("is_sponsored"), lead.get("outbound_link_count")
                    ),
                )
                if cur.rowcount:
                    inserted += 1
                    conn.execute(
                        """
                        INSERT INTO seen_opportunities (project_id, url_key, last_activity_at)
                        VALUES (%s, %s, timezone('utc', now()))
                        ON CONFLICT(project_id, url_key) DO UPDATE SET
                          last_activity_at = timezone('utc', now())
                        """,
                        (project_id, key),
                    )
            except sqlite3.IntegrityError:
                continue
        conn.commit()
    return inserted


def get_leads_by_status(
    status: str, limit: int = 50, project_id: int | None = None, db_path: str = DEFAULT_DB_PATH
) -> list[dict]:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        if project_id is not None:
            rows = conn.execute(
                "SELECT * FROM harvest_leads WHERE status=%s AND project_id=%s "
                "ORDER BY score_100 DESC, created_at ASC LIMIT %s",
                (status, project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM harvest_leads WHERE status=%s "
                "ORDER BY score_100 DESC, created_at ASC LIMIT %s",
                (status, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def update_lead(lead_id: int, fields: dict, db_path: str = DEFAULT_DB_PATH) -> None:
    """Update arbitrary columns on a lead (always bumps updated_at)."""
    if not fields:
        return
    init_whitelist_db(db_path)
    cols = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values())
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE harvest_leads SET {cols}, updated_at = timezone('utc', now()) WHERE id=%s",
            (*params, lead_id),
        )
        conn.commit()


def reset_failed_leads(
    project_id: int,
    *,
    to_status: str = "GATED",
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Reset FAILED harvest leads back to GATED (or another status) for retry."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE harvest_leads SET status=%s, draft_attempts = 0, run_id = NULL, "
            "updated_at = timezone('utc', now()) WHERE project_id=%s AND status = 'FAILED'",
            (to_status, project_id),
        )
        conn.commit()
        return cur.rowcount


def recover_stuck_drafted(
    minutes: int = 30,
    *,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Move DRAFTED leads stuck longer than `minutes` back to GATED."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE harvest_leads SET status = 'GATED', run_id = NULL, "
            "updated_at = timezone('utc', now()) "
            "WHERE status = 'DRAFTED' "
            "AND updated_at < NOW() AT TIME ZONE 'UTC' + CAST(%s AS INTERVAL)",
            (f"-{int(minutes)} minutes",),
        )
        conn.commit()
        return cur.rowcount


def count_leads_by_status(project_id: int | None = None, db_path: str = DEFAULT_DB_PATH) -> dict[str, int]:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        if project_id is not None:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM harvest_leads WHERE project_id=%s GROUP BY status",
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM harvest_leads GROUP BY status"
            ).fetchall()
    return {r["status"]: int(r["n"]) for r in rows}


def get_lead_by_url(project_id: int, url: str, db_path: str = DEFAULT_DB_PATH) -> dict | None:
    init_whitelist_db(db_path)
    key = str(url or "").lower().rstrip("/")
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM harvest_leads WHERE project_id=%s AND (url_key = %s OR url = %s) ORDER BY id DESC LIMIT 1",
            (project_id, key, url),
        ).fetchone()
    return dict(row) if row else None


def mark_seen_for_project_url(project_url: str, url: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Permanently mark a URL seen after editorial approve/reject."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT id FROM projects WHERE project_url=%s", (project_url.strip(),)).fetchone()
        if not row:
            return
        pid = int(row["id"])
    key = str(url or "").lower().rstrip("/")
    mark_seen_editorial(pid, key, db_path=db_path)


def purge_harvest_pipeline(
    project_id: int | None = None, db_path: str = DEFAULT_DB_PATH
) -> dict[str, int]:
    """Delete harvest_leads and seen_opportunities (fresh start). Keeps whitelist/projects."""
    init_whitelist_db(db_path)
    counts = {"harvest_leads": 0, "seen_opportunities": 0}
    with _connect(db_path) as conn:
        if project_id is not None:
            cur = conn.execute("DELETE FROM harvest_leads WHERE project_id=%s", (project_id,))
            counts["harvest_leads"] = cur.rowcount
            cur = conn.execute("DELETE FROM seen_opportunities WHERE project_id=%s", (project_id,))
            counts["seen_opportunities"] = cur.rowcount
        else:
            cur = conn.execute("DELETE FROM harvest_leads")
            counts["harvest_leads"] = cur.rowcount
            cur = conn.execute("DELETE FROM seen_opportunities")
            counts["seen_opportunities"] = cur.rowcount
        conn.commit()
    return counts


def reset_all_cooldowns(project_id: int | None = None, db_path: str = DEFAULT_DB_PATH) -> int:
    """Clear cooldown state and force all active sites due now."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        if project_id is not None:
            cur = conn.execute(
                """
                UPDATE whitelist_sites
                SET next_scan_due = timezone('utc', now()), cooldown_until = NULL,
                    failure_count = 0,
                    status = CASE WHEN status = 'cooldown' THEN 'active' ELSE status END
                WHERE project_id=%s AND status IN ('active', 'cooldown')
                """,
                (project_id,),
            )
        else:
            cur = conn.execute(
                """
                UPDATE whitelist_sites
                SET next_scan_due = timezone('utc', now()), cooldown_until = NULL,
                    failure_count = 0,
                    status = CASE WHEN status = 'cooldown' THEN 'active' ELSE status END
                WHERE status IN ('active', 'cooldown')
                """
            )
        conn.commit()
        return cur.rowcount


def get_project_id_by_url(project_url: str, db_path: str = DEFAULT_DB_PATH) -> int | None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT id FROM projects WHERE project_url=%s", (project_url.strip(),)).fetchone()
    return int(row["id"]) if row else None


def set_site_scan_priority(
    project_id: int, domain: str, priority: int, db_path: str = DEFAULT_DB_PATH
) -> bool:
    """Manual pin: set scan_priority 0-100 for a whitelisted domain."""
    init_whitelist_db(db_path)
    domain = domain.lower().strip().lstrip("www.")
    priority = max(0, min(100, int(priority)))
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE whitelist_sites SET scan_priority=%s WHERE project_id=%s AND domain=%s",
            (priority, project_id, domain),
        )
        conn.commit()
        return cur.rowcount > 0


def get_whitelist_site(project_id: int, domain: str, db_path: str = DEFAULT_DB_PATH) -> dict | None:
    init_whitelist_db(db_path)
    domain = domain.lower().strip().lstrip("www.")
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM whitelist_sites WHERE project_id=%s AND domain=%s",
            (project_id, domain),
        ).fetchone()
    return dict(row) if row else None


def resolve_whitelist_domain(project_id: int, domain_query: str, db_path: str = DEFAULT_DB_PATH) -> str | None:
    """Match user input like 'reddit', 'x', 'reddit.com/r/Bitcoin' to whitelist domain."""
    q = domain_query.lower().strip().lstrip("www.")
    sites = get_active_whitelist(project_id, db_path=db_path)
    if not q:
        return None
    aliases = {
        "twitter": "x.com", "x": "x.com", "reddit": "reddit.com",
        "hn": "news.ycombinator.com", "hackernews": "news.ycombinator.com",
    }
    if q in aliases:
        q = aliases[q]
    for s in sites:
        if s["domain"].lower() == q:
            return s["domain"]
    for s in sites:
        dom = s["domain"].lower()
        if q in dom or dom.startswith(q):
            return s["domain"]
    return None


def refresh_scan_priorities(project_id: int, db_path: str = DEFAULT_DB_PATH) -> int:
    """Recompute scan_priority from usability + recent lead yield. Never deactivates sites."""
    init_whitelist_db(db_path)
    updated = 0
    with _connect(db_path) as conn:
        sites = conn.execute(
            "SELECT id, domain, current_usability_score, scan_priority FROM whitelist_sites "
            "WHERE project_id=%s AND status IN ('active', 'cooldown')",
            (project_id,),
        ).fetchall()
        for site in sites:
            wl_id = site["id"]
            usability = float(site["current_usability_score"] or 50.0)
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM harvest_leads
                WHERE whitelist_site_id=%s AND created_at >= NOW() AT TIME ZONE 'UTC' + INTERVAL '-7 days'
                """,
                (wl_id,),
            ).fetchone()
            recent_leads = int(row["n"]) if row else 0
            yield_boost = min(recent_leads * 3, 30)
            # Preserve manual pins above 80
            manual = int(site["scan_priority"] or 50)
            if manual >= 80:
                new_prio = manual
            else:
                new_prio = int(max(10, min(100, usability * 0.5 + yield_boost + 20)))
            conn.execute(
                "UPDATE whitelist_sites SET scan_priority=%s WHERE id=%s",
                (new_prio, wl_id),
            )
            updated += 1
        conn.commit()
    return updated


def count_recent_leads(project_id: int, hours: int = 24, db_path: str = DEFAULT_DB_PATH) -> int:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM harvest_leads
            WHERE project_id=%s AND created_at >= NOW() AT TIME ZONE 'UTC' + CAST(%s || ' hours' AS INTERVAL)
            """,
            (project_id, f"-{hours}"),
        ).fetchone()
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------------------
# Flywheel: cursors, query stats, vocab, re-arm, domain candidates
# ---------------------------------------------------------------------------

def get_harvest_cursor(whitelist_site_id: int, db_path: str = DEFAULT_DB_PATH) -> dict:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT state_json FROM harvest_cursors WHERE whitelist_site_id=%s",
            (whitelist_site_id,),
        ).fetchone()
    if not row or not row["state_json"]:
        return {}
    try:
        return json.loads(row["state_json"])
    except (json.JSONDecodeError, TypeError):
        return {}


def set_harvest_cursor(whitelist_site_id: int, state: dict, db_path: str = DEFAULT_DB_PATH) -> None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO harvest_cursors (whitelist_site_id, state_json, updated_at)
            VALUES (%s, %s, timezone('utc', now()))
            ON CONFLICT(whitelist_site_id) DO UPDATE SET
              state_json = excluded.state_json,
              updated_at = timezone('utc', now())
            """,
            (whitelist_site_id, json.dumps(state, ensure_ascii=False)),
        )
        conn.commit()


def record_query_stats(
    project_id: int,
    domain: str,
    template_stats: dict[str, int],
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Upsert bandit stats: template_stats maps template_id -> new_leads this scan."""
    if not template_stats:
        return
    init_whitelist_db(db_path)
    dom = domain.lower().strip().lstrip("www.")
    with _connect(db_path) as conn:
        for tid, new_count in template_stats.items():
            conn.execute(
                """
                INSERT INTO query_stats (project_id, domain, template_id, runs, new_leads, last_used)
                VALUES (%s, %s, %s, 1, %s, timezone('utc', now()))
                ON CONFLICT(project_id, domain, template_id) DO UPDATE SET
                  runs = query_stats.runs + 1,
                  new_leads = query_stats.new_leads + excluded.new_leads,
                  last_used = timezone('utc', now())
                """,
                (project_id, dom, tid, int(new_count)),
            )
        conn.commit()


def get_query_stats(project_id: int, domain: str, db_path: str = DEFAULT_DB_PATH) -> dict[str, dict]:
    init_whitelist_db(db_path)
    dom = domain.lower().strip().lstrip("www.")
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT template_id, runs, new_leads FROM query_stats WHERE project_id=%s AND domain=%s",
            (project_id, dom),
        ).fetchall()
    return {r["template_id"]: {"runs": int(r["runs"]), "new_leads": int(r["new_leads"])} for r in rows}


def get_vocab_terms(project_id: int, limit: int = 30, db_path: str = DEFAULT_DB_PATH) -> list[str]:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT term FROM vocab_terms WHERE project_id=%s ORDER BY score DESC LIMIT %s",
            (project_id, limit),
        ).fetchall()
    return [r["term"] for r in rows]


def upsert_vocab_terms(
    project_id: int,
    terms: list[tuple[str, float, str]],
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Insert or bump score for mined terms. Returns count touched."""
    init_whitelist_db(db_path)
    n = 0
    with _connect(db_path) as conn:
        for term, score, source in terms:
            t = str(term).strip().lower()
            if not t or len(t) < 3:
                continue
            conn.execute(
                """
                INSERT INTO vocab_terms (project_id, term, score, source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(project_id, term) DO UPDATE SET
                  score = MAX(vocab_terms.score, excluded.score),
                  source = excluded.source
                """,
                (project_id, t, float(score), source),
            )
            n += 1
        conn.commit()
    return n


def revive_lead(project_id: int, url_key: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Re-arm an existing lead row to NEW (no duplicate insert)."""
    init_whitelist_db(db_path)
    key = str(url_key or "").lower().rstrip("/")
    with _connect(db_path) as conn:
        seen = conn.execute(
            """
            SELECT editorial_locked FROM seen_opportunities
            WHERE project_id=%s AND url_key=%s
            """,
            (project_id, key),
        ).fetchone()
        if seen and int(seen["editorial_locked"] or 0):
            return False
        cur = conn.execute(
            """
            UPDATE harvest_leads SET status = 'NEW', run_id = NULL, draft_attempts = 0,
              updated_at = timezone('utc', now())
            WHERE project_id=%s AND url_key=%s AND status IN ('SENT', 'REJECTED', 'GATED', 'SCORED', 'FAILED')
            """,
            (project_id, key),
        )
        conn.commit()
        return cur.rowcount > 0


def get_rearm_candidates(
    project_id: int,
    ttl_days: int = 21,
    limit: int = 20,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict]:
    """Leads eligible for re-arming (seen, not editorial locked, past TTL)."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT h.* FROM harvest_leads h
            JOIN seen_opportunities s ON s.project_id = h.project_id AND s.url_key = h.url_key
            WHERE h.project_id = %s
              AND COALESCE(s.editorial_locked, 0) = 0
              AND h.status IN ('SENT', 'REJECTED', 'GATED', 'SCORED', 'FAILED')
              AND CAST(s.first_seen_at AS timestamp) <= NOW() AT TIME ZONE 'UTC' + CAST(%s || ' days' AS INTERVAL)
            ORDER BY h.updated_at ASC
            LIMIT %s
            """,
            (project_id, f"-{int(ttl_days)}", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def queue_domain_candidate(
    project_id: int,
    domain: str,
    source_url: str = "",
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    init_whitelist_db(db_path)
    dom = domain.lower().strip().lstrip("www.")
    if not dom or "." not in dom:
        return False
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO domain_candidates (project_id, domain, source_url)
            VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (project_id, dom, source_url),
        )
        conn.commit()
        return cur.rowcount > 0


def promote_domain_candidates(project_id: int, limit: int = 3, db_path: str = DEFAULT_DB_PATH) -> int:
    """Promote pending domain candidates to whitelist. Returns count added."""
    init_whitelist_db(db_path)
    added = 0
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, domain FROM domain_candidates
            WHERE project_id=%s AND status = 'pending'
            ORDER BY created_at ASC LIMIT %s
            """,
            (project_id, limit),
        ).fetchall()
    for row in rows:
        upsert_whitelist_site(project_id, row["domain"], added_by="graph", db_path=db_path)
        with _connect(db_path) as conn:
            conn.execute(
                "UPDATE domain_candidates SET status = 'promoted' WHERE id=%s",
                (row["id"],),
            )
            conn.commit()
        added += 1
    return added


def get_existing_url_keys(project_id: int, db_path: str = DEFAULT_DB_PATH) -> set[str]:
    """All url_keys already in harvest_leads for skip during scan."""
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT url_key FROM harvest_leads WHERE project_id=%s",
            (project_id,),
        ).fetchall()
    return {str(r["url_key"]).lower() for r in rows}


# ---------------------------------------------------------------------------
# onboard_sessions — deterministic /onboard flow (backlink-onboarder plugin)
# ---------------------------------------------------------------------------

def _row_to_onboard_session(row: psycopg2.extras.DictRow) -> OnboardSession:
    return OnboardSession(
        id=row["id"],
        chat_id=row["chat_id"],
        user_id=row["user_id"],
        step=row["step"],
        answers_json=row["answers_json"],
        prompt_message_id=row["prompt_message_id"],
    )


def get_onboard_session(
    chat_id: str, user_id: str, *, db_path: str = DEFAULT_DB_PATH
) -> OnboardSession | None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM onboard_sessions WHERE chat_id=%s AND user_id=%s",
            (str(chat_id), str(user_id)),
        ).fetchone()
    return _row_to_onboard_session(row) if row else None


def get_any_onboard_session_for_chat(
    chat_id: str, *, db_path: str = DEFAULT_DB_PATH
) -> OnboardSession | None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM onboard_sessions WHERE chat_id=%s ORDER BY id DESC LIMIT 1",
            (str(chat_id),),
        ).fetchone()
    return _row_to_onboard_session(row) if row else None


def upsert_onboard_session(
    chat_id: str,
    user_id: str,
    step: str,
    *,
    answers_json: str = "{}",
    prompt_message_id: int | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO onboard_sessions (chat_id, user_id, step, answers_json, prompt_message_id, updated_at)
            VALUES (%s, %s, %s, %s, %s, timezone('utc', now()))
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
              step = excluded.step,
              answers_json = excluded.answers_json,
              prompt_message_id = excluded.prompt_message_id,
              updated_at = timezone('utc', now())
            """,
            (str(chat_id), str(user_id), step, answers_json, prompt_message_id),
        )
        conn.commit()


def clear_onboard_session(chat_id: str, user_id: str, *, db_path: str = DEFAULT_DB_PATH) -> None:
    init_whitelist_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM onboard_sessions WHERE chat_id=%s AND user_id=%s",
            (str(chat_id), str(user_id)),
        )
        conn.commit()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Whitelist DB helpers")
    parser.add_argument("--chat-id", dest="chat_id", help="Resolve project_url for a Telegram group id")
    args = parser.parse_args()
    if args.chat_id:
        url = resolve_project_for_group(args.chat_id)
        if url:
            print(url)
        else:
            print(f"no project bound to group {args.chat_id}", file=sys.stderr)
            raise SystemExit(1)
    else:
        parser.print_help()
        raise SystemExit(2)
