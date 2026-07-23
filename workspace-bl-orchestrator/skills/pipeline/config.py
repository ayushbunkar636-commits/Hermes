import os
import pathlib
import sys

def load_env(env_path=None):
    if not env_path:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
        env_path = os.path.join(root_dir, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key not in os.environ:
                    os.environ[key] = val

load_env()

BIFROST_BASE_URL = os.environ.get("BIFROST_BASE_URL", "https://placing-reliability-container-oecd.trycloudflare.com/v1")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "vertex/gemini-2.5-flash")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SUPABASE_CONNECTION_STRING = os.environ.get("SUPABASE_CONNECTION_STRING", os.environ.get("DATABASE_URL", ""))
BL_DB_PATH = os.environ.get("BL_DB_PATH", os.path.join(os.path.expanduser("~"), ".openclaw-backlink", "data", "backlink.db"))

class PostgresClient:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def cursor(self):
        import psycopg2.extras
        return self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    def execute(self, sql, parameters=()):
        import psycopg2.extras
        from psycopg2.errors import UniqueViolation
        is_ignore = "INSERT OR IGNORE" in sql
        c = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            c.execute(sql, parameters)
        except UniqueViolation:
            if is_ignore:
                self._conn.rollback()
            else:
                raise
        return c

    def executemany(self, sql, parameters_seq):
        import psycopg2.extras
        from psycopg2.errors import UniqueViolation
        is_ignore = "INSERT OR IGNORE" in sql
        c = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        if is_ignore:
            for p in parameters_seq:
                try:
                    c.execute(sql, p)
                except UniqueViolation:
                    self._conn.rollback()
        else:
            c.executemany(sql, parameters_seq)
        return c

    def executescript(self, sql):
        c = self._conn.cursor()
        c.execute(sql)
        return c

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

def get_db_connection():
    if SUPABASE_CONNECTION_STRING:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(SUPABASE_CONNECTION_STRING)
        return PostgresClient(conn)
    else:
        raise ValueError("SUPABASE_CONNECTION_STRING is not set in environment variables. Database connection failed.")

