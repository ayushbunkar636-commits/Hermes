#!/usr/bin/env python3
"""send_reminders.py - Pings Telegram groups for pending opportunities.

Rules:
- > 7 days: Auto archive
- > 72h & reminder_count < 2: Send stronger reminder
- > 48h & reminder_count < 1: Send standard reminder
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

import backlink_db
from build_and_send_card import load_bot_token, telegram_request
from pipeline_tz import now_sqlite

def _connect():
    backlink_db.init_db()
    return backlink_db._connect(backlink_db.DEFAULT_DB_PATH)

def send_telegram_reminder(chat_id: str, count: int, oldest_days: int) -> bool:
    token = load_bot_token()
    if not token or not chat_id:
        return False
    
    text = (
        "%s%s <b>Reminder</b>\n"
        f"{count} Opportunities still pending.\n"
        f"Oldest: {oldest_days} days.\n"
        "Please review them."
    )
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        telegram_request(token, "sendMessage", data=payload)
        return True
    except Exception as e:
        print(f"Failed to send reminder to {chat_id}: {e}", file=sys.stderr)
        return False

def process_reminders():
    now = datetime.utcnow()
    conn = _connect()
    
    # 1. Fetch all pending
    pending = conn.execute(
        "SELECT id, pending_since, card_sent_at, reminder_count, telegram_group FROM opportunities WHERE status = 'pending'"
    ).fetchall()
    
    settings = backlink_db.get_settings()
    intervals = settings.get("reminder_intervals_hours", {})
    archive_h = intervals.get("archive", 168)
    strong_h = intervals.get("strong", 72)
    standard_h = intervals.get("standard", 48)
    
    updates = []
    reminders_to_send = {}  # chat_id -> {"count": int, "oldest": int}
    
    for row in pending:
        opp_id = row["id"]
        chat_id = row["telegram_group"]
        rem_count = row["reminder_count"] or 0
        
        # Determine since when it's pending
        since_str = row["pending_since"] or row["card_sent_at"]
        if not since_str:
            continue
            
        try:
            since_dt = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
            # Remove timezone info for strict subtraction if it's naive UTC
            if since_dt.tzinfo:
                since_dt = since_dt.replace(tzinfo=None)
        except Exception:
            continue
            
        hours_elapsed = (now - since_dt).total_seconds() / 3600.0
        days_elapsed = int(hours_elapsed // 24)
        
        # Rule 1: Auto Archive
        if hours_elapsed > archive_h:
            updates.append({"id": opp_id, "status": "archived", "reminder_count": rem_count, "last_reminder": row.get("last_reminder")})
            continue
            
        trigger_reminder = False
        # Rule 2: Stronger reminder
        if hours_elapsed > strong_h and rem_count < 2:
            rem_count = 2
            trigger_reminder = True
        # Rule 3: Standard reminder
        elif hours_elapsed > standard_h and rem_count < 1:
            rem_count = 1
            trigger_reminder = True
            
        if trigger_reminder:
            updates.append({"id": opp_id, "status": "pending", "reminder_count": rem_count, "last_reminder": now_sqlite()})
            if chat_id not in reminders_to_send:
                reminders_to_send[chat_id] = {"count": 0, "oldest": days_elapsed}
            
            reminders_to_send[chat_id]["count"] += 1
            if days_elapsed > reminders_to_send[chat_id]["oldest"]:
                reminders_to_send[chat_id]["oldest"] = days_elapsed

    # Apply database updates
    if updates:
        with conn:
            for u in updates:
                conn.execute(
                    "UPDATE opportunities SET status = %s, reminder_count = %s, last_reminder = %s WHERE id = %s",
                    (u["status"], u["reminder_count"], u["last_reminder"], u["id"])
                )
    conn.close()
    
    # Fire Telegram messages
    for chat_id, data in reminders_to_send.items():
        send_telegram_reminder(chat_id, data["count"], max(1, data["oldest"]))
        print(f"Sent reminder to {chat_id}: {data['count']} pending.")

if __name__ == '__main__':
    process_reminders()
