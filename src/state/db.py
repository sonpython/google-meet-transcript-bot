import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    meet_code TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    scheduled_start_utc TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    transcript_path TEXT,
    summary_path TEXT,
    notes_path TEXT,
    audio_path TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    delivered_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS failures (
    component TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    last_at TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn
