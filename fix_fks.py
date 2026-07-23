import sys
import os

sys.path.insert(0, 'workspace-bl-orchestrator/skills/pipeline')
import config

def fix_fks():
    conn = config.get_db_connection()
    c = conn.cursor()
    
    # Fix feedback_events -> opportunities
    c.execute("ALTER TABLE feedback_events DROP CONSTRAINT IF EXISTS feedback_events_opportunity_id_fkey")
    c.execute("""
        ALTER TABLE feedback_events 
        ADD CONSTRAINT feedback_events_opportunity_id_fkey 
        FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
    """)
    
    # Fix opportunities -> projects
    c.execute("ALTER TABLE opportunities DROP CONSTRAINT IF EXISTS opportunities_project_id_fkey")
    c.execute("""
        ALTER TABLE opportunities 
        ADD CONSTRAINT opportunities_project_id_fkey 
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    """)
    
    # Fix leads -> projects
    c.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_project_id_fkey")
    c.execute("""
        ALTER TABLE leads 
        ADD CONSTRAINT leads_project_id_fkey 
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    """)
    
    # Fix project_sitemaps -> projects
    c.execute("ALTER TABLE project_sitemaps DROP CONSTRAINT IF EXISTS project_sitemaps_project_id_fkey")
    c.execute("""
        ALTER TABLE project_sitemaps 
        ADD CONSTRAINT project_sitemaps_project_id_fkey 
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    """)
    
    conn.commit()
    print("Successfully added ON DELETE CASCADE to all foreign keys.")
    conn.close()

if __name__ == "__main__":
    fix_fks()
