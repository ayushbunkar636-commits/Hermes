import os
import sys

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills", "pipeline")
sys.path.insert(0, _PIPELINE_DIR)

import config
import psycopg2

def clear_db():
    conn = config.get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM harvest_leads;")
            print(f"Deleted {cur.rowcount} rows from harvest_leads table.")
        conn.commit()
    except Exception as e:
        print(f"Error clearing db: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    clear_db()
