import sys
import os

# Add skills to path to import config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'workspace-bl-orchestrator', 'skills', 'pipeline'))
import config

schema = """
-- Phase 1: Relevancy & Sitemap Schema

CREATE TABLE IF NOT EXISTS project_sitemaps (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title TEXT,
    meta_description TEXT,
    page_type TEXT DEFAULT 'post', -- 'pillar' or 'post'
    embedding_vector JSONB, -- Will store vector representation for relevancy
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()),
    UNIQUE(project_id, url)
);

CREATE TABLE IF NOT EXISTS daily_trends (
    id SERIAL PRIMARY KEY,
    trend_query TEXT NOT NULL UNIQUE,
    trend_context TEXT,
    status TEXT DEFAULT 'active',
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now())
);
"""

def apply_schema():
    print("Applying V2 Relevancy Schema to PostgreSQL...")
    conn = config.get_db_connection()
    c = conn.cursor()
    try:
        c.execute(schema)
        conn.commit()
        print("SUCCESS: Schema applied successfully.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR: Error applying schema: {e}")
    finally:
        c.close()
        conn.close()

if __name__ == "__main__":
    apply_schema()
