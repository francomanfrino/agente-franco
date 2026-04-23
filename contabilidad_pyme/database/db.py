"""SQLite connection manager with WAL mode for better concurrency."""
import sqlite3
import os
from pathlib import Path

DB_PATH = Path(os.environ.get("CONTAB_DB_PATH", Path.home() / ".contabilidad_pyme" / "contabilidad.db"))


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    from database.models import CREATE_STATEMENTS
    conn = get_connection()
    with conn:
        for stmt in CREATE_STATEMENTS:
            conn.execute(stmt)
    conn.close()
