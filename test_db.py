import sys
sys.path.append('workspace-bl-orchestrator/skills/pipeline')
import config

conn = config.get_db_connection()
cur = conn.cursor()

try:
    cur.execute("""
      SELECT 
        p.id, p.project_url, p.niche, p.config_json, p.created_at, p.status,
        COALESCE(
          json_agg(
            json_build_object('id', w.id, 'domain', w.domain, 'site_type', w.site_type)
          ) FILTER (WHERE w.id IS NOT NULL),
          '[]'::json
        ) as sources
      FROM projects p
      LEFT JOIN project_whitelist pw ON p.id = pw.project_id
      LEFT JOIN whitelist_sites w ON pw.site_id = w.id
      GROUP BY p.id
      ORDER BY p.created_at DESC
    """)
    print("Query success! Found rows:", len(cur.fetchall()))
except Exception as e:
    print("Query failed:", str(e))
