"""Meeting query helpers shared by the admin HTTP server and the MCP server.

All helpers are argument-driven (no load_settings calls) so callers control
which database they hit and tests can monkeypatch settings freely.
"""

import json
import re
from datetime import datetime
from pathlib import Path


def first_param(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key) or []
    return values[0].strip() if values and values[0] is not None else ""


def bounded_int(value: str, default: int, minimum: int, maximum: int) -> int:
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("limit/offset must be integers") from exc
    return min(max(parsed, minimum), maximum)


def truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def range_boundary(value: str, end: bool) -> str:
    if not value:
        return ""
    raw = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return f"{raw}T23:59:59.999999" if end else f"{raw}T00:00:00"
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid date/time filter: {raw}") from exc


def normalize_meet_code(value: str) -> str | None:
    raw = value.strip().lower()
    match = re.search(r"([a-z]{3})-?([a-z]{4})-?([a-z]{3})", raw)
    if not match:
        return None
    return "-".join(match.groups())


def decode_attendees(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return [str(value)]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def meeting_filter_sql(params: dict[str, list[str]]) -> tuple[str, tuple]:
    clauses = []
    values: list[str] = []
    title = first_param(params, "title") or first_param(params, "name") or first_param(params, "q")
    if title:
        clauses.append("LOWER(title) LIKE ?")
        values.append(f"%{title.lower()}%")
    code = first_param(params, "meet_code") or first_param(params, "code")
    if code:
        meet_code = normalize_meet_code(code)
        if not meet_code:
            raise ValueError("invalid Meet code")
        clauses.append("meet_code = ?")
        values.append(meet_code)
    status = first_param(params, "status")
    if status:
        clauses.append("status = ?")
        values.append(status)
    # Convenience filter only: everyone can read every meeting, the attendee
    # match just narrows the view (matches attendees JSON and organizer).
    attendee = first_param(params, "attendee")
    if attendee:
        clauses.append("LOWER(COALESCE(attendees,'') || ' ' || COALESCE(organizer,'')) LIKE ?")
        values.append(f"%{attendee.strip().lower()}%")
    start_from = range_boundary(
        first_param(params, "from") or first_param(params, "start_from") or first_param(params, "date_from"),
        end=False,
    )
    start_to = range_boundary(
        first_param(params, "to") or first_param(params, "start_to") or first_param(params, "date_to"),
        end=True,
    )
    if start_from:
        clauses.append("scheduled_start_utc >= ?")
        values.append(start_from)
    if start_to:
        clauses.append("scheduled_start_utc <= ?")
        values.append(start_to)
    return ("WHERE " + " AND ".join(clauses) if clauses else "", tuple(values))


def resolve_meeting_paths(meeting: dict) -> dict[str, Path | None]:
    paths: dict[str, Path | None] = {
        "audio": path_or_none(meeting.get("audio_path")),
        "transcript": path_or_none(meeting.get("transcript_path")),
        "summary": path_or_none(meeting.get("summary_path")),
        "minutes": path_or_none(meeting.get("minutes_path")),
        "notes": path_or_none(meeting.get("notes_path")),
    }
    notes = paths["notes"]
    if paths["notes"] and paths["transcript"] and paths["notes"] == paths["transcript"]:
        paths["notes"] = None
        notes = None
    if notes and notes.name.startswith("meeting-notes-"):
        slug = notes.name.removeprefix("meeting-notes-").removesuffix(".md")
        paths["transcript"] = paths["transcript"] or notes.with_name(f"transcript-{slug}.md")
        paths["summary"] = paths["summary"] or notes.with_name(f"summary-{slug}.md")
        paths["minutes"] = paths["minutes"] or notes.with_name(f"meeting-minutes-{slug}.md")
    return paths


def path_or_none(value: str | None) -> Path | None:
    return Path(value) if value else None
