import sys
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_fixer")

sys.path.insert(0, 'workspace-bl-orchestrator/skills/pipeline')
try:
    import config
except ImportError as e:
    logger.error(f"Cannot import config: {e}")
    sys.exit(1)

def fix_fks():
    try:
        conn = config.get_db_connection()
        c = conn.cursor()
        
        logger.info("Applying ON DELETE CASCADE to all foreign keys dynamically...")
        
        # Query all foreign keys
        c.execute("""
            SELECT
                tc.table_name,
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM 
                information_schema.table_constraints AS tc 
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                  AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public';
        """)
        fks = c.fetchall()
        
        for fk in fks:
            table_name = fk["table_name"]
            constraint_name = fk["constraint_name"]
            column_name = fk["column_name"]
            foreign_table = fk["foreign_table_name"]
            foreign_column = fk["foreign_column_name"]
            
            c.execute(f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {constraint_name}")
            c.execute(f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} FOREIGN KEY ({column_name}) REFERENCES {foreign_table}({foreign_column}) ON DELETE CASCADE")
            
        conn.commit()
        conn.close()
        logger.info(f"Successfully upgraded {len(fks)} foreign keys to ON DELETE CASCADE.")
    except Exception as e:
        logger.error(f"Failed to apply DB fixes: {e}")

if __name__ == "__main__":
    fix_fks()
