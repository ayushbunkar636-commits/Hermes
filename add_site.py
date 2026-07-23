import sys
import os
sys.path.append('workspace-bl-orchestrator/skills/pipeline')
import config

conn = config.get_db_connection()
cur = conn.cursor()

# Find alien.fi project
cur.execute("SELECT id FROM projects WHERE project_url LIKE '%alien.fi%'")
proj = cur.fetchone()
if proj:
    project_id = proj[0]
    
    # Check if site exists, if not insert
    cur.execute("SELECT id FROM whitelist_sites WHERE domain='reddit.com/r/SaaS'")
    site = cur.fetchone()
    if not site:
        cur.execute("INSERT INTO whitelist_sites (domain, site_type, scan_priority) VALUES ('reddit.com/r/SaaS', 'forum', 10) RETURNING id")
        site_id = cur.fetchone()[0]
    else:
        site_id = site[0]
        
    # Link it
    cur.execute("SELECT * FROM project_whitelist WHERE project_id=%s AND site_id=%s", (project_id, site_id))
    if not cur.fetchone():
        cur.execute("INSERT INTO project_whitelist (project_id, site_id) VALUES (%s, %s)", (project_id, site_id))
    
    conn.commit()
    print("SUCCESS: Added reddit.com/r/SaaS to alien.fi whitelist!")
else:
    print("ERROR: alien.fi project not found.")
