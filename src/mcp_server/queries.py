"""Read-only meeting queries for the MCP server.

Opens the shared SQLite file with mode=ro so a tool bug can never write or
lock out the main process. Reuses the REST filter SQL so MCP and REST agree
on every filter's meaning.
"""

import sqlite3
from pathlib import Path

from src.state.meeting_queries import (
    decode_attendees,
    meeting_filter_sql,
    normalize_meet_code,
    resolve_meeting_paths,
)

MAX_TRANSCRIPT_CHARS = 400_000
TRUNCATION_MARKER = "\n\n[transcript truncated at 400000 characters]"
SNIPPET_CONTEXT_CHARS = 200

METADATA_COLUMNS = (
    "meet_code, event_id, title, status, organizer, attendees, "
    "scheduled_start_utc, scheduled_end_utc, actual_end_utc, delivered_at, "
    "created_at, updated_at"
)


def read_only_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_meetings(
    db_path: Path,
    date_from: str = "",
    date_to: str = "",
    query: str = "",
    attendee: str = "",
    status: str = "",
    limit: int = 20,
) -> list[dict]:
    params = _params(date_from=date_from, date_to=date_to, q=query, attendee=attendee, status=status)
    where, values = meeting_filter_sql(params)
    limit = min(max(int(limit), 1), 200)
    conn = read_only_connect(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT {METADATA_COLUMNS} FROM meetings {where}
            ORDER BY scheduled_start_utc DESC, updated_at DESC
            LIMIT ?
            """,
            (*values, limit),
        ).fetchall()
        return [_metadata(row) for row in rows]
    finally:
        conn.close()


def get_meeting(db_path: Path, meet_code: str) -> dict:
    row = _meeting_row(db_path, meet_code)
    payload = _metadata(row)
    paths = resolve_meeting_paths(dict(row))
    payload["summary"] = _read_file(paths.get("summary"))
    payload["meeting_minutes"] = _read_file(paths.get("minutes"))
    return payload


def read_transcript(db_path: Path, meet_code: str) -> str:
    row = _meeting_row(db_path, meet_code)
    content = _read_file(resolve_meeting_paths(dict(row)).get("transcript"))
    if content is None:
        return f"No transcript file is available for meeting {row['meet_code']} (status: {row['status']})."
    if len(content) > MAX_TRANSCRIPT_CHARS:
        return content[:MAX_TRANSCRIPT_CHARS] + TRUNCATION_MARKER
    return content


def search_transcripts(
    db_path: Path,
    query: str,
    date_from: str = "",
    date_to: str = "",
    attendee: str = "",
    limit: int = 10,
) -> list[dict]:
    term = query.strip()
    if not term:
        raise ValueError("query is required")
    limit = min(max(int(limit), 1), 50)
    params = _params(date_from=date_from, date_to=date_to, attendee=attendee)
    where, values = meeting_filter_sql(params)
    conn = read_only_connect(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM meetings {where}
            ORDER BY scheduled_start_utc DESC, updated_at DESC
            """,
            values,
        ).fetchall()
    finally:
        conn.close()
    hits: list[dict] = []
    lowered = term.lower()
    for row in rows:
        content = _read_file(resolve_meeting_paths(dict(row)).get("transcript"))
        if not content:
            continue
        index = content.lower().find(lowered)
        if index < 0:
            continue
        start = max(0, index - SNIPPET_CONTEXT_CHARS)
        end = min(len(content), index + len(term) + SNIPPET_CONTEXT_CHARS)
        hits.append(
            {
                "meet_code": row["meet_code"],
                "title": row["title"],
                "scheduled_start_utc": row["scheduled_start_utc"],
                "snippet": content[start:end].strip(),
            }
        )
        if len(hits) >= limit:
            break
    return hits


def _meeting_row(db_path: Path, meet_code: str) -> sqlite3.Row:
    normalized = normalize_meet_code(meet_code)
    if not normalized:
        raise ValueError(f"invalid Meet code: {meet_code}")
    conn = read_only_connect(db_path)
    try:
        row = conn.execute("SELECT * FROM meetings WHERE meet_code = ?", (normalized,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"meeting not found: {normalized}")
    return row


def _metadata(row: sqlite3.Row) -> dict:
    data = {key: row[key] for key in row.keys()}
    data["attendees"] = decode_attendees(data.get("attendees"))
    return {key: data.get(key) for key in (
        "meet_code", "event_id", "title", "status", "organizer", "attendees",
        "scheduled_start_utc", "scheduled_end_utc", "actual_end_utc",
        "delivered_at", "created_at", "updated_at",
    )}


def _read_file(path) -> str | None:
    if path is None:
        return None
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _params(**values: str) -> dict[str, list[str]]:
    return {key: [value] for key, value in values.items() if value}
