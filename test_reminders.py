import sys, os, sqlite3, datetime
sys.path.insert(0, "workspace-bl-orchestrator/skills/pipeline")
import backlink_db
from pipeline_tz import now_sqlite
backlink_db.init_db()

conn = sqlite3.connect(backlink_db.DEFAULT_DB_PATH)
conn.row_factory = sqlite3.Row

now = datetime.datetime.utcnow()
h49 = (now - datetime.timedelta(hours=49)).strftime("%Y-%m-%dT%H:%M:%SZ")
h73 = (now - datetime.timedelta(hours=73)).strftime("%Y-%m-%dT%H:%M:%SZ")
h200 = (now - datetime.timedelta(hours=200)).strftime("%Y-%m-%dT%H:%M:%SZ")

conn.execute("INSERT INTO opportunities (run_id, url, status, pending_since, telegram_group, telegram_message_id) VALUES (?, ?, ?, ?, ?, ?)", ("r1", "http://f1", "pending", h49, "test_chat", 1))
conn.execute("INSERT INTO opportunities (run_id, url, status, pending_since, telegram_group, telegram_message_id) VALUES (?, ?, ?, ?, ?, ?)", ("r2", "http://f2", "pending", h73, "test_chat", 2))
conn.execute("INSERT INTO opportunities (run_id, url, status, pending_since, telegram_group, telegram_message_id) VALUES (?, ?, ?, ?, ?, ?)", ("r3", "http://f3", "pending", h200, "test_chat", 3))
conn.commit()
conn.close()

print("Inserted test DB entries.")
