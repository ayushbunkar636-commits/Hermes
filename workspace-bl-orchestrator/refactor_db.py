import os
import re

files = [
    r'workspace-bl-orchestrator\skills\pipeline\backlink_db.py',
    r'workspace-bl-orchestrator\skills\pipeline\whitelist_db.py'
]

for file in files:
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replace sqlite3 imports
    content = content.replace('import sqlite3', 'import psycopg2\nimport psycopg2.extras\nimport os')
    
    # Replace connect functions
    connect_func_pattern = re.compile(r'def _connect\(.*?\).*?:')
    content = re.sub(
        connect_func_pattern, 
        '''def _connect(db_path: str = None):
    conn = psycopg2.connect(
        os.environ.get("DATABASE_URL", "postgresql://postgres.mcbuijwyxmanqjjcanme:ayushbunkar100@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres?pgbouncer=true")
    )
    conn.autocommit = False
    return conn''', 
        content
    )

    # Replace parameter binding
    # We carefully replace ? with %s when not inside quotes.
    # A simple regex works for standard queries if they don't have ? in strings.
    # Fortunately, most queries in these files use standard ? binding.
    content = content.replace('?', '%s')
    
    # Replace sqlite3.Row with psycopg2.extras.DictRow / RealDictCursor
    content = content.replace('sqlite3.Row', 'psycopg2.extras.DictRow')
    content = content.replace('sqlite3.Connection', 'psycopg2.extensions.connection')
    
    # Remove AUTOINCREMENT in SQLite and replace with Postgres SERIAL (Wait, these are already in Postgres schema so we don't even need the CREATE TABLE IF NOT EXISTS scripts to run locally, but it's safe to just replace AUTOINCREMENT)
    content = content.replace('AUTOINCREMENT', '')
    
    # Update dict conversion for psycopg2 DictRow
    # DictRow works like dict, but let's change dict(row) or dict(r) if any.
    # Actually, if we use RealDictCursor we can return dicts directly.
    content = content.replace('conn.execute', 'conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor).execute')
    content = content.replace('conn.cursor()', 'conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)')
    
    with open(file, 'w', encoding='utf-8') as f:
        f.write(content)

print('Refactored DB files to use psycopg2.')
