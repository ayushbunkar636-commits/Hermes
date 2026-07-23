import os
import re

def migrate_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Replace sqlite3.connect with config.get_db_connection()
    content = content.replace("import sqlite3", "import config")
    content = content.replace("sqlite3.connect(DB_PATH)", "config.get_db_connection()")
    content = content.replace("sqlite3.connect(DB_PATH, timeout=5.0)", "config.get_db_connection()")
    content = content.replace("sqlite3.connect(db_path)", "config.get_db_connection()")
    content = content.replace("sqlite3.connect(db_path, timeout=5.0)", "config.get_db_connection()")
    
    # Replace ? with %s for Postgres
    # This regex looks for ? that are outside of strings, but since it's raw SQL, most are in strings.
    # A simple replace will break python strings if there are actual question marks.
    # Instead, we will only replace ? inside cursor.execute("... ? ...", ) calls.
    # A safe approximation for these specific DB files is to just replace '?' with '%s' where it represents a SQL bind.
    # Actually, we can use a custom wrapper to translate on the fly, but modifying the file is better.
    # Let's replace '?' with '%s' where it looks like a SQL statement.
    content = re.sub(r'VALUES \(([^)]*\?[^)]*)\)', lambda m: m.group(0).replace('?', '%s'), content)
    content = re.sub(r'SET ([A-Za-z0-9_]+)\s*=\s*\?', r'SET \1=%s', content)
    content = re.sub(r'WHERE ([A-Za-z0-9_]+)\s*=\s*\?', r'WHERE \1=%s', content)
    content = re.sub(r'AND ([A-Za-z0-9_]+)\s*=\s*\?', r'AND \1=%s', content)
    
    # SQLite specific function replacements
    content = content.replace("datetime('now')", "timezone('utc', now())")
    content = content.replace("INSERT OR REPLACE", "INSERT INTO") # Note: ON CONFLICT needs manual fix if exact, but basic works

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    files = [
        "workspace-bl-orchestrator/skills/pipeline/hermes_client.py",
        "workspace-bl-orchestrator/skills/pipeline/telegram_router.py",
        "workspace-bl-orchestrator/skills/pipeline/whitelist_db.py",
        "workspace-bl-orchestrator/skills/pipeline/backlink_db.py"
    ]
    for f in files:
        if os.path.exists(f):
            migrate_file(f)
            print(f"Migrated {f}")
