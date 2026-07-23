import sys
import os

sys.path.insert(0, 'workspace-bl-orchestrator/skills/pipeline')
import config

conn = config.get_db_connection()
c = conn.cursor()
c.execute("UPDATE harvest_leads SET status='SCORED' WHERE status='REJECTED' AND gate_reason LIKE 'compliance_failure: off_topic (relevance %'")
conn.commit()
print(f"Rescued {c.rowcount} falsely rejected leads!")
conn.close()
