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
    meeting_end_confirmed INTEGER NOT NULL DEFAULT 0,
    meeting_end_reason TEXT,
    admin_instruction TEXT,
    processing_status TEXT,
    processing_stage TEXT,
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

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    password_hash TEXT,
    api_key_hash TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS users_api_key_hash_idx
    ON users(api_key_hash) WHERE api_key_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS api_keys_user_idx ON api_keys(user_id);

-- One-time move of the legacy single-key column into api_keys. Clearing the
-- column afterwards is what makes this idempotent: a revoked key must not be
-- resurrected from users.api_key_hash on the next connect.
INSERT INTO api_keys (user_id, name, key_hash)
    SELECT id, 'default', api_key_hash FROM users
    WHERE api_key_hash IS NOT NULL
      AND api_key_hash NOT IN (SELECT key_hash FROM api_keys);
UPDATE users SET api_key_hash = NULL WHERE api_key_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS user_sessions_user_idx ON user_sessions(user_id);
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
    _ensure_column(conn, "meetings", "meeting_end_confirmed", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "meetings", "meeting_end_reason", "TEXT")
    _ensure_column(conn, "meetings", "admin_instruction", "TEXT")
    _ensure_column(conn, "meetings", "processing_status", "TEXT")
    _ensure_column(conn, "meetings", "processing_stage", "TEXT")
    _ensure_column(conn, "meetings", "processing_batch", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "meetings", "processing_total", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "meetings", "processing_error", "TEXT")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.commit()
