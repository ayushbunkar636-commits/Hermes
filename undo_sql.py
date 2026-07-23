import os
import re

def undo_migrate(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Revert %s back to ?
    content = content.replace('%s', '?')
    
    # Revert Postgres timezone back to SQLite datetime
    content = content.replace("timezone('utc', now())", "datetime('now')")
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    files = [
        "workspace-bl-orchestrator/skills/pipeline/whitelist_db.py",
        "workspace-bl-orchestrator/skills/pipeline/backlink_db.py"
    ]
    for f in files:
        if os.path.exists(f):
            undo_migrate(f)
            print(f"Reverted {f}")
