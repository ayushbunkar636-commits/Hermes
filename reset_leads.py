import sys
sys.path.append('workspace-bl-orchestrator/skills/pipeline')
import config

conn = config.get_db_connection()
cur = conn.cursor()

try:
    cur.execute("UPDATE harvest_leads SET status = 'GATED', draft_attempts = 0 WHERE status = 'FAILED'")
    conn.commit()
    print("Successfully reset FAILED leads back to GATED. They will be drafted again.")
except Exception as e:
    print("Failed:", str(e))
