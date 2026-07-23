#!/usr/bin/env python3
"""backlink_db.py — SQLite store for backlink opportunities and feedback."""
from __future__ import annotations

import json
import os
import config
import psycopg2
import psycopg2.extras
import os
from dataclasses import dataclass
from typing import Any

from pipeline_tz import hours_ago_sqlite, now_sqlite  # noqa: E402

DEFAULT_DB_PATH = os.path.expanduser("~/.openclaw-backlink/data/backlink.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
  id INTEGER PRIMARY KEY ,
  run_id TEXT NOT NULL,
  alert_id TEXT NOT NULL,
  niche TEXT,
  project_url TEXT,
  project_name TEXT,
  site_url TEXT NOT NULL,
  site_domain TEXT,
  site_type TEXT,
  audit_score REAL,
  domain_authority INTEGER,
  dofollow INTEGER,
  recommendation TEXT,
  audit_notes TEXT,
  content_title TEXT,
  content_md TEXT,
  backlink_url TEXT,
  backlink_anchor_text TEXT,
  image_path TEXT,
  submission_instructions TEXT,
  submission_url TEXT,
  target_title TEXT,
  target_excerpt TEXT,
  opportunity_context TEXT,
  opportunity_freshness TEXT,
  posting_action TEXT,
  posting_steps TEXT,
  telegram_group TEXT NOT NULL,
  telegram_message_id INTEGER NOT NULL,
  card_sent_at TEXT,
  run_dir TEXT,
  status TEXT DEFAULT 'pending',
  score_breakdown TEXT,
  confidence INTEGER,
  reasoning TEXT,
  business_impact TEXT,
  last_reminder TEXT,
  reminder_count INTEGER DEFAULT 0,
  pending_since TEXT,
  created_at TEXT DEFAULT (timezone('utc', now()))
);
CREATE INDEX IF NOT EXISTS idx_bl_tg_msg ON opportunities(telegram_group, telegram_message_id);
CREATE INDEX IF NOT EXISTS idx_bl_run ON opportunities(run_id);
CREATE INDEX IF NOT EXISTS idx_bl_alert ON opportunities(alert_id);

CREATE TABLE IF NOT EXISTS feedback_events (
  id INTEGER PRIMARY KEY ,
  opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
  event_type TEXT NOT NULL,
  user_id TEXT,
  user_username TEXT,
  source TEXT NOT NULL,
  raw_payload TEXT,
  edited_content TEXT,
  created_at TEXT DEFAULT (timezone('utc', now()))
);
CREATE INDEX IF NOT EXISTS idx_bl_feedback ON feedback_events(opportunity_id, event_type);

CREATE TABLE IF NOT EXISTS content_versions (
  id INTEGER PRIMARY KEY ,
  opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
  version_type TEXT NOT NULL,
  content_md TEXT NOT NULL,
  user_id TEXT,
  user_username TEXT,
  created_at TEXT DEFAULT (timezone('utc', now()))
);
CREATE INDEX IF NOT EXISTS idx_bl_versions ON content_versions(opportunity_id, version_type);

CREATE TABLE IF NOT EXISTS edit_sessions (
  id INTEGER PRIMARY KEY ,
  opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
  user_id TEXT NOT NULL,
  state TEXT NOT NULL,
  prompt_message_id INTEGER,
  suggested_version_id INTEGER,
  created_at TEXT DEFAULT (timezone('utc', now())),
  UNIQUE(opportunity_id, user_id)
);
CREATE TABLE IF NOT EXISTS system_settings (
  id INTEGER PRIMARY KEY,
  min_score INTEGER DEFAULT 80,
  platforms TEXT DEFAULT '["reddit", "news"]',
  reminder_intervals_hours TEXT DEFAULT '{"standard":48, "strong":72, "archive":168}',
  ai_model TEXT DEFAULT 'vertex/gemini-2.5-flash',
  schedule_frequency_minutes INTEGER DEFAULT 60,
  telegram_formatting TEXT DEFAULT '',
  business_thresholds TEXT DEFAULT '{}',
  learning_enabled INTEGER DEFAULT 1,
  last_heartbeat TEXT DEFAULT (timezone('utc', now()))
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY ,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  is_read INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (timezone('utc', now()))
);
"""


@dataclass
class Opportunity:
    id: int
    run_id: str
    alert_id: str
    niche: str | None
    project_url: str | None
    project_name: str | None
    site_url: str
    site_domain: str | None
    site_type: str | None
    audit_score: float | None
    domain_authority: int | None
    dofollow: bool | None
    recommendation: str | None
    audit_notes: str | None
    content_title: str | None
    content_md: str | None
    backlink_url: str | None
    backlink_anchor_text: str | None
    image_path: str | None
    submission_instructions: str | None
    telegram_group: str
    telegram_message_id: int
    card_sent_at: str | None
    submission_url: str | None = None
    target_title: str | None = None
    target_excerpt: str | None = None
    opportunity_context: str | None = None
    opportunity_freshness: str | None = None
    posting_action: str | None = None
    posting_steps: str | None = None
    run_dir: str | None = None
    status: str = "pending"
    score_100: float | None = None
    rank: int | None = None
    score_breakdown: str | None = None
    confidence: int | None = None
    reasoning: str | None = None
    business_impact: str | None = None
    last_reminder: str | None = None
    reminder_count: int = 0
    pending_since: str | None = None


@dataclass
class EditSession:
    id: int
    opportunity_id: int
    user_id: str
    state: str
    prompt_message_id: int | None
    suggested_version_id: int | None


@dataclass
class ContentVersion:
    id: int
    opportunity_id: int
    version_type: str
    content_md: str
    user_id: str | None
    user_username: str | None


def _connect(db_path: str = None):
    return config.get_db_connection()


# Additive columns introduced after the original schema. Each is applied with
# ALTER TABLE ... ADD COLUMN only if missing, so existing databases migrate
# in place without losing rows.
_OPPORTUNITY_MIGRATIONS: dict[str, str] = {
    "submission_url": "ALTER TABLE opportunities ADD COLUMN submission_url TEXT",
    "target_title": "ALTER TABLE opportunities ADD COLUMN target_title TEXT",
    "target_excerpt": "ALTER TABLE opportunities ADD COLUMN target_excerpt TEXT",
    "opportunity_context": "ALTER TABLE opportunities ADD COLUMN opportunity_context TEXT",
    "opportunity_freshness": "ALTER TABLE opportunities ADD COLUMN opportunity_freshness TEXT",
    "posting_action": "ALTER TABLE opportunities ADD COLUMN posting_action TEXT",
    "posting_steps": "ALTER TABLE opportunities ADD COLUMN posting_steps TEXT",
    "score_100": "ALTER TABLE opportunities ADD COLUMN score_100 REAL",
    "rank": "ALTER TABLE opportunities ADD COLUMN rank INTEGER",
    "score_breakdown": "ALTER TABLE opportunities ADD COLUMN score_breakdown TEXT",
    "confidence": "ALTER TABLE opportunities ADD COLUMN confidence INTEGER",
    "reasoning": "ALTER TABLE opportunities ADD COLUMN reasoning TEXT",
    "business_impact": "ALTER TABLE opportunities ADD COLUMN business_impact TEXT",
    "last_reminder": "ALTER TABLE opportunities ADD COLUMN last_reminder TEXT",
    "reminder_count": "ALTER TABLE opportunities ADD COLUMN reminder_count INTEGER DEFAULT 0",
    "pending_since": "ALTER TABLE opportunities ADD COLUMN pending_since TEXT",
}


def utc_now_sqlite() -> str:
    """Deprecated alias — use now_sqlite() (IST)."""
    return now_sqlite()


def _ensure_columns(conn: psycopg2.extensions.connection) -> None:
    existing = {row["column_name"] for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'opportunities'")}
    if not existing:
        return
    for column, ddl in _OPPORTUNITY_MIGRATIONS.items():
        if column not in existing:
            conn.execute(ddl)


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        _ensure_columns(conn)
        # Ensure default settings row exists (handled by frontend registration)
        conn.commit()


def _row_get(row: psycopg2.extras.DictRow, key: str, default=None):
    return row[key] if key in row.keys() else default


def _row_to_opportunity(row: psycopg2.extras.DictRow) -> Opportunity:
    return Opportunity(
        id=row["id"],
        run_id=row["run_id"],
        alert_id=row["alert_id"],
        niche=row["niche"],
        project_url=row["project_url"],
        project_name=row["project_name"],
        site_url=row["site_url"],
        site_domain=row["site_domain"],
        site_type=row["site_type"],
        audit_score=row["audit_score"],
        domain_authority=row["domain_authority"],
        dofollow=bool(row["dofollow"]) if row["dofollow"] is not None else None,
        recommendation=row["recommendation"],
        audit_notes=row["audit_notes"],
        content_title=row["content_title"],
        content_md=row["content_md"],
        backlink_url=row["backlink_url"],
        backlink_anchor_text=row["backlink_anchor_text"],
        image_path=row["image_path"],
        submission_instructions=row["submission_instructions"],
        submission_url=_row_get(row, "submission_url"),
        target_title=_row_get(row, "target_title"),
        target_excerpt=_row_get(row, "target_excerpt"),
        opportunity_context=_row_get(row, "opportunity_context"),
        opportunity_freshness=_row_get(row, "opportunity_freshness"),
        posting_action=_row_get(row, "posting_action"),
        posting_steps=_row_get(row, "posting_steps"),
        telegram_group=row["telegram_group"],
        telegram_message_id=row["telegram_message_id"],
        card_sent_at=row["card_sent_at"],
        run_dir=row["run_dir"],
        status=row["status"] or "pending",
        score_100=_row_get(row, "score_100"),
        rank=_row_get(row, "rank"),
    )


def insert_opportunity(card: dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> int:
    init_db(db_path)
    run_id = str(card.get("run_id") or "").strip()
    alert_id = str(card.get("alert_id") or f"bl-{run_id}-{card.get('site_domain','')}")
    group = str(card.get("telegram_group") or "").strip()
    message_id = card.get("telegram_message_id")
    if not run_id or not group or message_id is None:
        raise ValueError("run_id, telegram_group, telegram_message_id required")

    posting_steps = card.get("posting_steps")
    if isinstance(posting_steps, list):
        posting_steps = json.dumps(posting_steps, ensure_ascii=False)
    elif posting_steps is not None:
        posting_steps = str(posting_steps)

    with _connect(db_path) as conn:
        c = conn.execute(
            """
            INSERT INTO opportunities (
              run_id, alert_id, niche, project_url, project_name,
              site_url, site_domain, site_type, audit_score, domain_authority,
              dofollow, recommendation, audit_notes, content_title, content_md,
              backlink_url, backlink_anchor_text, image_path, submission_instructions,
              submission_url, target_title, target_excerpt, opportunity_context,
              opportunity_freshness, posting_action, posting_steps,
              telegram_group, telegram_message_id, card_sent_at, run_dir, status,
              score_100, rank, score_breakdown, confidence, reasoning, business_impact,
              last_reminder, reminder_count, pending_since
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (
                run_id,
                alert_id,
                str(card.get("niche") or "") or None,
                str(card.get("project_url") or "") or None,
                str(card.get("project_name") or "") or None,
                str(card.get("site_url") or ""),
                str(card.get("site_domain") or "") or None,
                str(card.get("site_type") or "") or None,
                card.get("audit_score"),
                card.get("domain_authority"),
                1 if card.get("dofollow") else 0 if card.get("dofollow") is not None else None,
                str(card.get("recommendation") or "") or None,
                str(card.get("audit_notes") or "") or None,
                str(card.get("content_title") or "") or None,
                str(card.get("content_md") or "") or None,
                str(card.get("backlink_url") or "") or None,
                str(card.get("backlink_anchor_text") or "") or None,
                str(card.get("image_path") or "") or None,
                str(card.get("submission_instructions") or "") or None,
                str(card.get("submission_url") or "") or None,
                str(card.get("target_title") or "") or None,
                str(card.get("target_excerpt") or "") or None,
                str(card.get("opportunity_context") or "") or None,
                str(card.get("opportunity_freshness") or "") or None,
                str(card.get("posting_action") or "") or None,
                posting_steps,
                group,
                int(message_id),
                str(card.get("card_sent_at") or utc_now_sqlite()) or None,
                str(card.get("run_dir") or "") or None,
                str(card.get("status") or "pending"),
                card.get("score_100"),
                card.get("rank"),
                json.dumps(card.get("score_breakdown")) if isinstance(card.get("score_breakdown"), dict) else card.get("score_breakdown"),
                card.get("confidence"),
                json.dumps(card.get("reasoning")) if isinstance(card.get("reasoning"), list) else card.get("reasoning"),
                json.dumps(card.get("business_impact")) if isinstance(card.get("business_impact"), dict) else card.get("business_impact"),
                card.get("last_reminder"),
                card.get("reminder_count") or 0,
                card.get("pending_since") or card.get("card_sent_at")
            ),
        )
        conn.commit()
        row = c.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


def set_status(opportunity_id: int, status: str, db_path: str = DEFAULT_DB_PATH) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("UPDATE opportunities SET status=%s WHERE id=%s", (status, opportunity_id))
        conn.commit()


def prune_old_archives(days: int = 30, db_path: str = DEFAULT_DB_PATH) -> int:
    with _connect(db_path) as conn:
        cutoff = hours_ago_sqlite(days * 24)
        c = conn.execute("DELETE FROM opportunities WHERE status = 'archived' AND card_sent_at < %s", (cutoff,))
        conn.commit()
        return c.rowcount

def get_settings(user_id: int = 1, db_path: str = None) -> dict[str, Any]:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM system_settings WHERE user_id = %s", (user_id,)).fetchone()
        if not row:
            return {
                "min_score": 80,
                "platforms": ["reddit", "news"],
                "reminder_intervals_hours": {"standard": 48, "strong": 72, "archive": 168},
                "ai_model": "vertex/gemini-2.5-flash",
                "schedule_frequency_minutes": 60,
                "telegram_formatting": "",
                "business_thresholds": {},
                "learning_enabled": True
            }
        import json
        return {
            "min_score": row["min_score"],
            "platforms": json.loads(row["platforms"] or "[]"),
            "reminder_intervals_hours": json.loads(row["reminder_intervals_hours"] or "{}"),
            "ai_model": row["ai_model"],
            "schedule_frequency_minutes": row["schedule_frequency_minutes"],
            "telegram_formatting": row["telegram_formatting"],
            "business_thresholds": json.loads(row["business_thresholds"] or "{}"),
            "learning_enabled": bool(row["learning_enabled"])
        }

def update_settings(user_id: int, updates: dict[str, Any], db_path: str = None) -> None:
    import json
    with _connect(db_path) as conn:
        fields = []
        values = []
        for k, v in updates.items():
            if k in ["platforms", "reminder_intervals_hours", "business_thresholds"]:
                v = json.dumps(v)
            if k == "learning_enabled":
                v = 1 if v else 0
            fields.append(f"{k} = %s")
            values.append(v)
        
        if fields:
            query = f"UPDATE system_settings SET {', '.join(fields)} WHERE user_id = %s"
            values.append(user_id)
            conn.execute(query, tuple(values))
            conn.commit()

def update_heartbeat(db_path: str = None) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE system_settings SET last_heartbeat = CURRENT_TIMESTAMP")
        conn.commit()


def add_notification(type: str, title: str, message: str, db_path: str = DEFAULT_DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO notifications (type, title, message) VALUES (%s, %s, %s)",
            (type, title, message)
        )
        conn.commit()

def get_notifications(limit: int = 50, offset: int = 0, db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM notifications ORDER BY created_at DESC LIMIT %s OFFSET %s", 
            (limit, offset)
        ).fetchall()
        return [dict(r) for r in rows]

def mark_notification_read(notif_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE notifications SET is_read = 1 WHERE id = %s", (notif_id,))
        conn.commit()


def lookup_by_message_id(
    telegram_group: str, message_id: int, db_path: str = DEFAULT_DB_PATH
) -> Opportunity | None:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM opportunities WHERE telegram_group=%s AND telegram_message_id=%s ORDER BY id DESC LIMIT 1",
            (str(telegram_group), int(message_id)),
        ).fetchone()
    return _row_to_opportunity(row) if row else None


def lookup_by_run_id(run_id: str, db_path: str = DEFAULT_DB_PATH) -> Opportunity | None:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM opportunities WHERE run_id=%s ORDER BY id DESC LIMIT 1",
            (run_id.strip(),),
        ).fetchone()
    return _row_to_opportunity(row) if row else None


def lookup_by_alert_id(alert_id: str, db_path: str = DEFAULT_DB_PATH) -> Opportunity | None:
    init_db(db_path)
    aid = alert_id.strip()
    if not aid.startswith("bl-"):
        aid = f"bl-{aid}"
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM opportunities WHERE alert_id=%s", (aid,)).fetchone()
    return _row_to_opportunity(row) if row else None


def record_feedback(
    opportunity_id: int,
    event_type: str,
    *,
    user_id: str | None = None,
    user_username: str | None = None,
    source: str = "callback",
    raw_payload: str | None = None,
    edited_content: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    if event_type not in ("approve", "reject", "edit", "edit_apply", "edit_cancel"):
        raise ValueError(f"invalid event_type: {event_type}")
    init_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO feedback_events (
              opportunity_id, event_type, user_id, user_username, source, raw_payload, edited_content
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (opportunity_id, event_type, user_id, user_username, source, raw_payload, edited_content),
        )
        conn.commit()
        return int(cur.lastrowid)


def save_content_version(
    opportunity_id: int,
    version_type: str,
    content_md: str,
    *,
    user_id: str | None = None,
    user_username: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    if version_type not in ("published_snapshot", "user_suggested", "applied"):
        raise ValueError(f"invalid version_type: {version_type}")
    init_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO content_versions (
              opportunity_id, version_type, content_md, user_id, user_username
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (opportunity_id, version_type, content_md, user_id, user_username),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_latest_version(
    opportunity_id: int, version_type: str, db_path: str = DEFAULT_DB_PATH
) -> ContentVersion | None:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM content_versions WHERE opportunity_id=%s AND version_type=%s ORDER BY id DESC LIMIT 1",
            (opportunity_id, version_type),
        ).fetchone()
    if not row:
        return None
    return ContentVersion(
        id=row["id"],
        opportunity_id=row["opportunity_id"],
        version_type=row["version_type"],
        content_md=row["content_md"],
        user_id=row["user_id"],
        user_username=row["user_username"],
    )


def upsert_edit_session(
    opportunity_id: int,
    user_id: str,
    state: str,
    *,
    prompt_message_id: int | None = None,
    suggested_version_id: int | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO edit_sessions (
              opportunity_id, user_id, state, prompt_message_id, suggested_version_id
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(opportunity_id, user_id) DO UPDATE SET
              state = excluded.state,
              prompt_message_id = excluded.prompt_message_id,
              suggested_version_id = excluded.suggested_version_id
            """,
            (opportunity_id, user_id, state, prompt_message_id, suggested_version_id),
        )
        conn.commit()


def get_edit_session_by_prompt(
    prompt_message_id: int, db_path: str = DEFAULT_DB_PATH
) -> tuple[EditSession, Opportunity] | None:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM edit_sessions WHERE prompt_message_id=%s ORDER BY id DESC LIMIT 1",
            (int(prompt_message_id),),
        ).fetchone()
        if not row:
            return None
        session = EditSession(
            id=row["id"],
            opportunity_id=row["opportunity_id"],
            user_id=row["user_id"],
            state=row["state"],
            prompt_message_id=row["prompt_message_id"],
            suggested_version_id=row["suggested_version_id"],
        )
        opp_row = conn.execute(
            "SELECT * FROM opportunities WHERE id=%s", (session.opportunity_id,)
        ).fetchone()
    return (session, _row_to_opportunity(opp_row)) if opp_row else None


def clear_edit_session(opportunity_id: int, user_id: str, db_path: str = DEFAULT_DB_PATH) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM edit_sessions WHERE opportunity_id=%s AND user_id=%s",
            (opportunity_id, user_id),
        )
        conn.commit()


def clear_all_edit_sessions(opportunity_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM edit_sessions WHERE opportunity_id=%s", (opportunity_id,))
        conn.commit()


def resolve_opportunity_content(opp: Opportunity, db_path: str = DEFAULT_DB_PATH) -> str | None:
    """Canonical draft text: applied edit > content_md > legacy published_snapshot."""
    applied = get_latest_version(opp.id, "applied", db_path)
    if applied and applied.content_md.strip():
        return applied.content_md
    if opp.content_md and opp.content_md.strip():
        return opp.content_md
    snap = get_latest_version(opp.id, "published_snapshot", db_path)
    if snap and snap.content_md.strip():
        return snap.content_md
    return None


def get_pending_opportunities(
    project_url: str,
    *,
    limit: int = 5,
    db_path: str = DEFAULT_DB_PATH,
) -> list[Opportunity]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM opportunities
            WHERE status = 'pending' AND project_url=%s
            ORDER BY card_sent_at ASC
            LIMIT %s
            """,
            (project_url.strip(), int(limit)),
        ).fetchall()
    return [_row_to_opportunity(r) for r in rows]


def update_opportunity_delivery(
    opportunity_id: int,
    telegram_message_id: int,
    card_sent_at: str,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE opportunities
            SET telegram_message_id=%s, card_sent_at = %s
            WHERE id=%s
            """,
            (int(telegram_message_id), card_sent_at, opportunity_id),
        )
        conn.commit()


def get_stale_pending_opportunities(
    hours: float = 24.0,
    project_url: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> list[Opportunity]:
    """Return pending cards older than `hours` (candidates for resurface)."""
    init_db(db_path)
    cutoff = hours_ago_sqlite(hours)
    with _connect(db_path) as conn:
        if project_url:
            rows = conn.execute(
                """
                SELECT * FROM opportunities
                WHERE status = 'pending'
                  AND project_url=%s
                  AND card_sent_at IS NOT NULL
                  AND card_sent_at <= %s
                ORDER BY card_sent_at ASC
                """,
                (project_url.strip(), cutoff),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM opportunities
                WHERE status = 'pending'
                  AND card_sent_at IS NOT NULL
                  AND card_sent_at <= %s
                ORDER BY card_sent_at ASC
                """,
                (cutoff,),
            ).fetchall()
    return [_row_to_opportunity(r) for r in rows]


def purge_editorial_data(
    project_url: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, int]:
    """Delete opportunities + related editorial rows. Returns counts deleted."""
    init_db(db_path)
    counts = {"opportunities": 0, "feedback": 0, "versions": 0, "edit_sessions": 0}
    with _connect(db_path) as conn:
        if project_url:
            opp_ids = [
                r["id"] for r in conn.execute(
                    "SELECT id FROM opportunities WHERE project_url=%s", (project_url.strip(),)
                ).fetchall()
            ]
        else:
            opp_ids = [r["id"] for r in conn.execute("SELECT id FROM opportunities").fetchall()]
        if opp_ids:
            placeholders = ",".join("%s" * len(opp_ids))
            cur = conn.execute(
                f"DELETE FROM feedback_events WHERE opportunity_id IN ({placeholders})", opp_ids
            )
            counts["feedback"] = cur.rowcount
            cur = conn.execute(
                f"DELETE FROM content_versions WHERE opportunity_id IN ({placeholders})", opp_ids
            )
            counts["versions"] = cur.rowcount
            cur = conn.execute(
                f"DELETE FROM edit_sessions WHERE opportunity_id IN ({placeholders})", opp_ids
            )
            counts["edit_sessions"] = cur.rowcount
        if project_url:
            cur = conn.execute("DELETE FROM opportunities WHERE project_url=%s", (project_url.strip(),))
        else:
            cur = conn.execute("DELETE FROM opportunities")
        counts["opportunities"] = cur.rowcount
        conn.commit()
    return counts
