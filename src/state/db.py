import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    meet_code TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    scheduled_start_utc TEXT NOT NULL,
    scheduled_end_utc TEXT,
    title TEXT NOT NULL,
    organizer TEXT,
    attendees TEXT,
    status TEXT NOT NULL,
    transcript_path TEXT,
    summary_path TEXT,
    minutes_path TEXT,
    notes_path TEXT,
    audio_path TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    delivered_at TEXT,
    actual_end_utc TEXT,
    processing_status TEXT,
    processing_batch INTEGER NOT NULL DEFAULT 0,
    processing_total INTEGER NOT NULL DEFAULT 0,
    processing_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS failures (
    component TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    last_at TEXT
);

CREATE TABLE IF NOT EXISTS admin_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    meet_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _ensure_column(conn, "meetings", "minutes_path", "TEXT")
    _ensure_column(conn, "meetings", "organizer", "TEXT")
    _ensure_column(conn, "meetings", "attendees", "TEXT")
    _ensure_column(conn, "meetings", "scheduled_end_utc", "TEXT")
    _ensure_column(conn, "meetings", "actual_end_utc", "TEXT")
    _ensure_column(conn, "meetings", "processing_status", "TEXT")
    _ensure_column(conn, "meetings", "processing_batch", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "meetings", "processing_total", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "meetings", "processing_error", "TEXT")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.commit()
