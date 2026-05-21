import json
import os
import re
import subprocess
from datetime import UTC, datetime
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from sqlite3 import Row
from urllib.parse import parse_qs, unquote, urlparse

from src.auth.oauth_user import OAuthUserAuth
from src.auth.token_store import TokenStore
from src.calendar_watcher.classifier import to_meeting_event
from src.calendar_watcher.client import CalendarClient
from src.config import load_settings
from src.models.meeting_event import MeetingEvent
from src.runtime_status import STATUS
from src.state.db import connect
from src.state.meetings_repo import TERMINAL_STATUSES, MeetingsRepo


class AdminHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/status", "/healthz"):
            self._send_json(STATUS.snapshot())
            return
        if parsed.path == "/admin":
            if not self._is_authorized(parsed):
                self._send_html(_login_html())
                return
            self._send_html(_admin_html())
            return
        if parsed.path == "/admin/settings":
            if not self._is_authorized(parsed):
                self._send_html(_login_html())
                return
            self._send_html(_settings_html())
            return
        if parsed.path.startswith("/admin/api/"):
            if not self._is_authorized(parsed):
                self._send_json({"error": "unauthorized"}, status=401)
                return
            self._handle_api(parsed)
            return
        if parsed.path.startswith("/api/"):
            if not self._is_authorized(parsed, allow_cookie=False):
                self._send_json({"error": "unauthorized"}, status=401)
                return
            self._handle_public_api(parsed)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/admin/login":
            self._handle_login()
            return
        if parsed.path.startswith("/admin/api/"):
            if not self._is_authorized(parsed):
                self._send_json({"error": "unauthorized"}, status=401)
                return
            self._handle_api_post(parsed)
            return
        if parsed.path.startswith("/api/"):
            self._send_json({"error": "method not allowed"}, status=405)
            return
        self.send_error(404)

    def _handle_login(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8")
        token = parse_qs(body).get("token", [""])[0]
        if token and token == (load_settings().admin_token or ""):
            self.send_response(303)
            self.send_header("Location", "/admin")
            self.send_header("Set-Cookie", f"admin_token={token}; Path=/admin; HttpOnly; SameSite=Lax")
            self.end_headers()
            return
        self._send_html(_login_html("Invalid token"), status=401)

    def _handle_api(self, parsed) -> None:
        suffix = parsed.path.removeprefix("/admin/api/")
        try:
            if suffix == "status":
                self._send_json(STATUS.snapshot())
            elif suffix == "meetings":
                self._send_json({"meetings": _list_meetings()})
            elif suffix == "settings":
                self._send_json({"settings": _admin_settings()})
            elif suffix.startswith("meetings/") and suffix.endswith("/audio-meta"):
                meet_code = unquote(suffix.removeprefix("meetings/").removesuffix("/audio-meta"))
                detail = _meeting_detail(meet_code, include_audio_peaks=True)
                self._send_json({"audio_segments": detail.get("files", {}).get("audio_segments", [])})
            elif suffix.startswith("meetings/") and suffix.endswith("/audio"):
                meet_code = unquote(suffix.removeprefix("meetings/").removesuffix("/audio"))
                index = int(parse_qs(parsed.query).get("index", ["0"])[0] or "0")
                self._send_audio(meet_code, index)
            elif suffix.startswith("meetings/"):
                self._send_json({"meeting": _meeting_detail(unquote(suffix.removeprefix("meetings/")))})
            elif suffix == "upcoming":
                self._send_json({"events": _upcoming_events()})
            else:
                self._send_json({"error": "not found"}, status=404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _handle_public_api(self, parsed) -> None:
        suffix = parsed.path.removeprefix("/api/")
        params = parse_qs(parsed.query)
        try:
            if suffix == "meetings":
                self._send_json(_api_list_meetings(params))
            elif suffix.startswith("meetings/"):
                meet_code = _normalize_meet_code(unquote(suffix.removeprefix("meetings/")))
                if not meet_code:
                    self._send_json({"error": "invalid Meet code"}, status=400)
                    return
                self._send_json({"meeting": _api_meeting_detail(meet_code)})
            elif suffix == "transcripts":
                self._send_json(_api_transcripts(params))
            else:
                self._send_json({"error": "not found"}, status=404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _handle_api_post(self, parsed) -> None:
        suffix = parsed.path.removeprefix("/admin/api/")
        if suffix == "manual-join":
            self._send_json(_request_manual_join(self._read_json_body()))
            return
        if suffix == "settings/audio-retention":
            self._send_json(_update_audio_retention(self._read_json_body()))
            return
        if suffix.startswith("meetings/") and suffix.endswith("/rejoin"):
            meet_code = unquote(suffix.removeprefix("meetings/").removesuffix("/rejoin"))
            self._send_json(_request_rejoin(meet_code))
            return
        if suffix.startswith("meetings/") and suffix.endswith("/force-out"):
            meet_code = unquote(suffix.removeprefix("meetings/").removesuffix("/force-out"))
            self._send_json(_request_force_out(meet_code))
            return
        if suffix.startswith("meetings/") and suffix.endswith("/regenerate"):
            meet_code = unquote(suffix.removeprefix("meetings/").removesuffix("/regenerate"))
            self._send_json(_request_regenerate(meet_code, self._read_json_body()))
            return
        self._send_json({"error": "not found"}, status=404)

    def _is_authorized(self, parsed, allow_cookie: bool = True) -> bool:
        expected = load_settings().admin_token
        if not expected:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth.removeprefix("Bearer ").strip() == expected:
            return True
        if self.headers.get("X-API-Key", "").strip() == expected:
            return True
        if self.headers.get("X-Admin-Token", "").strip() == expected:
            return True
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        if query_token == expected:
            return True
        if not allow_cookie:
            return False
        raw_cookie = self.headers.get("Cookie", "")
        if raw_cookie:
            parsed_cookie = cookies.SimpleCookie(raw_cookie)
            morsel = parsed_cookie.get("admin_token")
            if morsel and morsel.value == expected:
                return True
        return False

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body or "{}")

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_audio(self, meet_code: str, index: int = 0) -> None:
        detail = _meeting_detail(meet_code)
        segments = detail.get("files", {}).get("audio_segments", [])
        audio = segments[index] if 0 <= index < len(segments) else detail.get("files", {}).get("audio", {})
        path = Path(audio.get("path", ""))
        if not audio.get("exists") or not path.exists():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/ogg; codecs=opus")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 256):
                self.wfile.write(chunk)

    def log_message(self, format: str, *args) -> None:
        return


def _list_meetings() -> list[dict]:
    settings = load_settings()
    conn = connect(settings.db_path)
    try:
        rows = conn.execute(
            """
            SELECT meet_code, event_id, scheduled_start_utc, scheduled_end_utc, actual_end_utc, title, status,
                   organizer, attendees,
                   transcript_path, summary_path, minutes_path, notes_path, audio_path,
                   meeting_end_confirmed, meeting_end_reason, admin_instruction,
                   processing_status, processing_stage, processing_batch, processing_total, processing_error,
                   attempts, last_error, delivered_at, created_at, updated_at
            FROM meetings
            ORDER BY scheduled_start_utc DESC, updated_at DESC
            LIMIT 200
            """
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def _api_list_meetings(params: dict[str, list[str]]) -> dict:
    limit = _bounded_int(_first_param(params, "limit"), default=50, minimum=1, maximum=200)
    offset = _bounded_int(_first_param(params, "offset"), default=0, minimum=0, maximum=100_000)
    include_content = _truthy(_first_param(params, "include_content"))
    rows = _query_meetings(params, limit=limit, offset=offset)
    total = _count_meetings(params)
    return {
        "meetings": [_api_meeting_payload(_row_to_dict(row), include_content=include_content) for row in rows],
        "pagination": {"limit": limit, "offset": offset, "count": len(rows), "total": total},
        "filters": _api_filter_echo(params),
    }


def _api_meeting_detail(meet_code: str) -> dict:
    return _api_meeting_payload(_meeting_detail(meet_code), include_content=True)


def _api_transcripts(params: dict[str, list[str]]) -> dict:
    rows = _query_meetings(params, limit=_bounded_int(_first_param(params, "limit"), 20, 1, 100), offset=0)
    meetings = [_api_meeting_payload(_meeting_detail(row["meet_code"]), include_content=True) for row in rows]
    return {"meetings": meetings, "count": len(meetings), "filters": _api_filter_echo(params)}


def _query_meetings(params: dict[str, list[str]], limit: int, offset: int) -> list[Row]:
    settings = load_settings()
    where, values = _meeting_filter_sql(params)
    conn = connect(settings.db_path)
    try:
        return list(
            conn.execute(
                f"""
                SELECT *
                FROM meetings
                {where}
                ORDER BY scheduled_start_utc DESC, updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (*values, limit, offset),
            ).fetchall()
        )
    finally:
        conn.close()


def _count_meetings(params: dict[str, list[str]]) -> int:
    settings = load_settings()
    where, values = _meeting_filter_sql(params)
    conn = connect(settings.db_path)
    try:
        row = conn.execute(f"SELECT COUNT(*) AS total FROM meetings {where}", values).fetchone()
        return int(row["total"] if row else 0)
    finally:
        conn.close()


def _meeting_filter_sql(params: dict[str, list[str]]) -> tuple[str, tuple]:
    clauses = []
    values: list[str] = []
    title = _first_param(params, "title") or _first_param(params, "name") or _first_param(params, "q")
    if title:
        clauses.append("LOWER(title) LIKE ?")
        values.append(f"%{title.lower()}%")
    code = _first_param(params, "meet_code") or _first_param(params, "code")
    if code:
        meet_code = _normalize_meet_code(code)
        if not meet_code:
            raise ValueError("invalid Meet code")
        clauses.append("meet_code = ?")
        values.append(meet_code)
    status = _first_param(params, "status")
    if status:
        clauses.append("status = ?")
        values.append(status)
    start_from = _range_boundary(
        _first_param(params, "from") or _first_param(params, "start_from") or _first_param(params, "date_from"),
        end=False,
    )
    start_to = _range_boundary(
        _first_param(params, "to") or _first_param(params, "start_to") or _first_param(params, "date_to"),
        end=True,
    )
    if start_from:
        clauses.append("scheduled_start_utc >= ?")
        values.append(start_from)
    if start_to:
        clauses.append("scheduled_start_utc <= ?")
        values.append(start_to)
    return ("WHERE " + " AND ".join(clauses) if clauses else "", tuple(values))


def _api_meeting_payload(meeting: dict, include_content: bool = False) -> dict:
    detail = meeting if "files" in meeting else _meeting_detail(str(meeting["meet_code"]))
    files = detail.get("files", {})
    metadata = {
        "meet_code": detail.get("meet_code"),
        "event_id": detail.get("event_id"),
        "title": detail.get("title"),
        "status": detail.get("status"),
        "organizer": detail.get("organizer"),
        "attendees": detail.get("attendees", []),
        "scheduled_start_utc": detail.get("scheduled_start_utc"),
        "scheduled_end_utc": detail.get("scheduled_end_utc"),
        "actual_end_utc": detail.get("actual_end_utc"),
        "meeting_end_confirmed": bool(detail.get("meeting_end_confirmed")),
        "meeting_end_reason": detail.get("meeting_end_reason"),
        "admin_instruction": detail.get("admin_instruction"),
        "processing_status": detail.get("processing_status"),
        "processing_stage": detail.get("processing_stage"),
        "processing_batch": detail.get("processing_batch"),
        "processing_total": detail.get("processing_total"),
        "processing_error": detail.get("processing_error"),
        "delivered_at": detail.get("delivered_at"),
        "attempts": detail.get("attempts"),
        "last_error": detail.get("last_error"),
        "created_at": detail.get("created_at"),
        "updated_at": detail.get("updated_at"),
    }
    payload = dict(metadata)
    payload["metadata"] = metadata
    payload["files"] = {key: _public_file_payload(value, include_content) for key, value in files.items()}
    if include_content:
        payload["transcript"] = files.get("transcript", {}).get("content")
        payload["summary"] = files.get("summary", {}).get("content")
        payload["meeting_minutes"] = files.get("minutes", {}).get("content")
        payload["notes"] = files.get("notes", {}).get("content")
    return payload


def _public_file_payload(file_payload: dict, include_content: bool) -> dict:
    if isinstance(file_payload, list):
        return [_public_file_payload(item, include_content) for item in file_payload]
    payload = {key: value for key, value in file_payload.items() if key != "content"}
    if include_content and "content" in file_payload:
        payload["content"] = file_payload["content"]
    return payload


def _api_filter_echo(params: dict[str, list[str]]) -> dict:
    keys = ("q", "title", "name", "meet_code", "code", "status", "from", "to", "start_from", "start_to", "date_from", "date_to")
    return {key: _first_param(params, key) for key in keys if _first_param(params, key)}


def _first_param(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key) or []
    return values[0].strip() if values and values[0] is not None else ""


def _bounded_int(value: str, default: int, minimum: int, maximum: int) -> int:
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("limit/offset must be integers") from exc
    return min(max(parsed, minimum), maximum)


def _truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _range_boundary(value: str, end: bool) -> str:
    if not value:
        return ""
    raw = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return f"{raw}T23:59:59.999999" if end else f"{raw}T00:00:00"
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid date/time filter: {raw}") from exc


def _meeting_detail(meet_code: str, include_audio_peaks: bool = False) -> dict:
    settings = load_settings()
    conn = connect(settings.db_path)
    try:
        row = conn.execute("SELECT * FROM meetings WHERE meet_code=?", (meet_code,)).fetchone()
        if not row:
            raise ValueError("meeting not found")
        meeting = _row_to_dict(row)
    finally:
        conn.close()

    paths = _meeting_paths(meeting)
    files = {}
    for key, path in paths.items():
        files[key] = _file_payload(path)
    files["audio_segments"] = _audio_segment_payloads(
        _audio_segment_paths(meet_code, settings.audio_dir),
        include_peaks=include_audio_peaks,
    )
    meeting["files"] = files
    meeting["metadata"] = {
        "meet_code": meeting.get("meet_code"),
        "event_id": meeting.get("event_id"),
        "organizer": meeting.get("organizer"),
        "attendees": meeting.get("attendees"),
        "status": meeting.get("status"),
        "scheduled_start_utc": meeting.get("scheduled_start_utc"),
        "scheduled_end_utc": meeting.get("scheduled_end_utc"),
        "actual_end_utc": meeting.get("actual_end_utc"),
        "meeting_end_confirmed": bool(meeting.get("meeting_end_confirmed")),
        "meeting_end_reason": meeting.get("meeting_end_reason"),
        "admin_instruction": meeting.get("admin_instruction"),
        "processing_status": meeting.get("processing_status"),
        "processing_stage": meeting.get("processing_stage"),
        "processing_batch": meeting.get("processing_batch"),
        "processing_total": meeting.get("processing_total"),
        "processing_error": meeting.get("processing_error"),
        "delivered_at": meeting.get("delivered_at"),
        "updated_at": meeting.get("updated_at"),
    }
    return meeting


def _request_rejoin(meet_code: str) -> dict:
    settings = load_settings()
    conn = connect(settings.db_path)
    try:
        repo = MeetingsRepo(conn)
        meeting = repo.get(meet_code)
        if not meeting:
            return {"error": "meeting not found"}
        if meeting["status"] in {"joining", "recording"}:
            return {"error": f"meeting already {meeting['status']}"}
        command_id = repo.request_rejoin(meet_code)
        return {"ok": True, "command_id": command_id, "meet_code": meet_code}
    finally:
        conn.close()


def _request_manual_join(payload: dict) -> dict:
    meet_code = _normalize_meet_code(str(payload.get("meet_code") or payload.get("url") or ""))
    if not meet_code:
        return {"error": "invalid Meet code"}
    settings = load_settings()
    now = datetime.now(UTC)
    calendar_meeting = _find_calendar_meeting(meet_code, settings)
    conn = connect(settings.db_path)
    try:
        repo = MeetingsRepo(conn)
        meeting = repo.get(meet_code)
        if calendar_meeting:
            if meeting:
                repo.mark_status(
                    meet_code,
                    "scheduled" if meeting["status"] in TERMINAL_STATUSES else meeting["status"],
                    None,
                    event_id=calendar_meeting.event_id,
                    scheduled_start_utc=calendar_meeting.start_utc.isoformat(),
                    scheduled_end_utc=calendar_meeting.end_utc.isoformat() if calendar_meeting.end_utc else None,
                    title=calendar_meeting.title,
                    organizer=calendar_meeting.organizer,
                    attendees=json.dumps(list(calendar_meeting.attendees), ensure_ascii=False),
                )
            else:
                repo.upsert(calendar_meeting)
            meeting = repo.get(meet_code)
        if meeting and meeting["status"] in {"joining", "recording"}:
            return {
                "error": f"meeting already {meeting['status']}",
                "meet_code": meet_code,
                "meeting": _row_to_dict(meeting),
            }
        repo.upsert(
            calendar_meeting
            or MeetingEvent(
                meet_code=meet_code,
                event_id=f"manual:{meet_code}:{int(now.timestamp())}",
                start_utc=now,
                end_utc=None,
                title=f"Manual Meet {meet_code}",
                organizer=settings.user_email,
                attendees=(),
            )
        )
        command_id = repo.request_rejoin(meet_code)
        return {"ok": True, "command_id": command_id, "meet_code": meet_code, "meeting": _row_to_dict(repo.get(meet_code))}
    finally:
        conn.close()


def _request_force_out(meet_code: str) -> dict:
    settings = load_settings()
    conn = connect(settings.db_path)
    try:
        repo = MeetingsRepo(conn)
        meeting = repo.get(meet_code)
        if not meeting:
            return {"error": "meeting not found"}
        if meeting["status"] != "recording":
            return {"error": f"meeting is {meeting['status']}, not recording"}
        command_id = repo.request_force_out(meet_code)
        return {"ok": True, "command_id": command_id, "meet_code": meet_code}
    finally:
        conn.close()


def _request_regenerate(meet_code: str, payload: dict) -> dict:
    settings = load_settings()
    instruction = str(payload.get("admin_instruction") or "").strip()
    if not instruction:
        return {"error": "admin instruction is required"}
    conn = connect(settings.db_path)
    try:
        repo = MeetingsRepo(conn)
        meeting = repo.get(meet_code)
        if not meeting:
            return {"error": "meeting not found"}
        if meeting["status"] in {"joining", "recording"}:
            return {"error": f"meeting is {meeting['status']}; end it before regenerating"}
        repo.set_admin_instruction(meet_code, instruction)
        repo.mark_processing(meet_code, "queued", 0, 3, stage="queued")
        command_id = repo.request_regenerate(meet_code)
        return {"ok": True, "command_id": command_id, "meet_code": meet_code}
    finally:
        conn.close()


def _normalize_meet_code(value: str) -> str | None:
    raw = value.strip().lower()
    match = re.search(r"([a-z]{3})-?([a-z]{4})-?([a-z]{3})", raw)
    if not match:
        return None
    return "-".join(match.groups())


def _find_calendar_meeting(meet_code: str, settings) -> MeetingEvent | None:
    try:
        token_store = TokenStore(settings.token_store_path, settings.token_passphrase)
        auth = OAuthUserAuth(token_store, str(settings.google_oauth_client_secrets), settings.oauth_redirect_port)
        client = CalendarClient(auth.get_credentials(), settings.calendar_id)
        for raw in client.list_upcoming(settings.calendar_lookahead_minutes):
            raw_code = _event_meet_code(raw)
            if raw_code != meet_code:
                continue
            return to_meeting_event(raw, settings.user_email) or _calendar_event_to_meeting(raw, meet_code)
    except Exception:
        return None
    return None


def _calendar_event_to_meeting(event: dict, meet_code: str) -> MeetingEvent | None:
    raw_start = event.get("start", {}).get("dateTime")
    if not raw_start:
        return None
    start_utc = datetime.fromisoformat(raw_start.replace("Z", "+00:00")).astimezone(UTC)
    attendees = tuple(
        attendee["email"]
        for attendee in event.get("attendees", [])
        if isinstance(attendee, dict) and attendee.get("email")
    )
    organizer = event.get("organizer", {}).get("email") if isinstance(event.get("organizer"), dict) else None
    return MeetingEvent(
        meet_code=meet_code,
        event_id=str(event.get("id", "")),
        start_utc=start_utc,
        end_utc=_parse_calendar_end(event),
        title=str(event.get("summary") or "Untitled meeting"),
        organizer=organizer,
        attendees=attendees,
    )


def _parse_calendar_end(event: dict) -> datetime | None:
    raw_end = event.get("end", {}).get("dateTime")
    if not raw_end:
        return None
    return datetime.fromisoformat(raw_end.replace("Z", "+00:00")).astimezone(UTC)


def _event_meet_code(event: dict) -> str | None:
    if event.get("hangoutLink"):
        return _normalize_meet_code(str(event["hangoutLink"]))
    for entry in event.get("conferenceData", {}).get("entryPoints", []):
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return _normalize_meet_code(str(entry["uri"]))
    return None


def _admin_settings() -> dict:
    settings = load_settings()
    conn = connect(settings.db_path)
    try:
        repo = MeetingsRepo(conn)
        return {
            "audio_retention_days": repo.get_audio_retention_days(settings.audio_retention_days),
        }
    finally:
        conn.close()


def _update_audio_retention(payload: dict) -> dict:
    settings = load_settings()
    raw_days = payload.get("audio_retention_days")
    try:
        days = int(raw_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("audio_retention_days must be an integer") from exc
    if days < 0 or days > 3650:
        raise ValueError("audio_retention_days must be between 0 and 3650")
    conn = connect(settings.db_path)
    try:
        repo = MeetingsRepo(conn)
        repo.set_setting("audio_retention_days", str(days))
        return {"ok": True, "settings": {"audio_retention_days": days}}
    finally:
        conn.close()


def _meeting_paths(meeting: dict) -> dict[str, Path | None]:
    paths: dict[str, Path | None] = {
        "audio": _path_or_none(meeting.get("audio_path")),
        "transcript": _path_or_none(meeting.get("transcript_path")),
        "summary": _path_or_none(meeting.get("summary_path")),
        "minutes": _path_or_none(meeting.get("minutes_path")),
        "notes": _path_or_none(meeting.get("notes_path")),
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


def _audio_segment_paths(meet_code: str, audio_dir: Path) -> list[Path]:
    if not audio_dir.exists():
        return []
    paths = sorted(audio_dir.glob(f"{meet_code}*.opus"), key=lambda path: path.stat().st_mtime)
    return paths


def _audio_segment_payloads(paths: list[Path], include_peaks: bool = False) -> list[dict]:
    payloads = []
    cursor = 0
    for index, path in enumerate(paths):
        payload = _file_payload(path)
        payload["index"] = index
        payload["duration_seconds"] = _audio_duration_seconds(path) if payload.get("exists") else 0
        payload["peaks"] = _audio_peaks(path) if include_peaks and payload.get("exists") and payload["duration_seconds"] else []
        payload["start_second"] = cursor
        cursor += int(payload["duration_seconds"] or 0)
        payload["end_second"] = cursor
        payloads.append(payload)
    return payloads


def _audio_duration_seconds(path: Path) -> int:
    if not path.exists() or path.stat().st_size <= 0:
        return 0
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
        return max(0, int(float(proc.stdout.strip() or "0")))
    except Exception:
        return 0


def _audio_peaks(path: Path, samples: int = 80) -> list[int]:
    if not path.exists() or path.stat().st_size <= 0:
        return []
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "8000",
                "-f",
                "s16le",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
    except Exception:
        return []
    raw = proc.stdout
    if not raw:
        return []
    frame_count = len(raw) // 2
    if frame_count <= 0:
        return []
    bucket_size = max(1, frame_count // samples)
    peaks = []
    max_peak = 1
    for bucket_start in range(0, frame_count, bucket_size):
        bucket_end = min(frame_count, bucket_start + bucket_size)
        peak = 0
        for index in range(bucket_start, bucket_end):
            value = int.from_bytes(raw[index * 2 : index * 2 + 2], "little", signed=True)
            peak = max(peak, abs(value))
        peaks.append(peak)
        max_peak = max(max_peak, peak)
        if len(peaks) >= samples:
            break
    return [max(2, min(100, round((peak / max_peak) * 100))) for peak in peaks]


def _file_payload(path: Path | None) -> dict:
    if not path:
        return {"exists": False}
    payload = {"path": str(path), "exists": path.exists()}
    if path.exists():
        payload["size"] = path.stat().st_size
        if path.suffix.lower() in {".md", ".txt", ".json"}:
            payload["content"] = path.read_text(errors="replace")
    return payload


def _upcoming_events() -> list[dict]:
    settings = load_settings()
    token_store = TokenStore(settings.token_store_path, settings.token_passphrase)
    auth = OAuthUserAuth(token_store, str(settings.google_oauth_client_secrets), settings.oauth_redirect_port)
    client = CalendarClient(auth.get_credentials(), settings.calendar_id)
    conn = connect(settings.db_path)
    events = []
    try:
        repo = MeetingsRepo(conn)
        for raw in client.list_upcoming(settings.calendar_lookahead_minutes):
            meeting = to_meeting_event(raw, settings.user_email)
            raw_meet_code = _event_meet_code(raw)
            stored = repo.get(meeting.meet_code if meeting else raw_meet_code) if (meeting or raw_meet_code) else None
            stored_status = stored["status"] if stored else None
            events.append(
                {
                    "event_id": raw.get("id"),
                    "title": raw.get("summary") or "Untitled meeting",
                    "start": raw.get("start"),
                    "end": raw.get("end"),
                    "meet_code": meeting.meet_code if meeting else raw_meet_code,
                    "organizer": raw.get("organizer"),
                    "attendees": raw.get("attendees", []),
                    "hangoutLink": raw.get("hangoutLink"),
                    "status": stored_status,
                    "qualifying": meeting is not None and stored_status not in TERMINAL_STATUSES,
                }
            )
        return events
    finally:
        conn.close()


def _row_to_dict(row) -> dict:
    data = {key: row[key] for key in row.keys()}
    if "attendees" in data:
        data["attendees"] = _decode_attendees(data.get("attendees"))
    return data


def _decode_attendees(value) -> list[str]:
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


def _path_or_none(value: str | None) -> Path | None:
    return Path(value) if value else None


def _json_default(value):
    if isinstance(value, (datetime, Path)):
        return str(value)
    return str(value)


def _login_html(error: str = "") -> str:
    error_html = f"<p class='error'>{error}</p>" if error else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Meeting Assistant Admin</title>{_style()}</head>
<body class="login"><form method="post" action="/admin/login" class="login-box">
<h1>Meeting Assistant</h1><label for="adminToken">Admin token</label><input id="adminToken" name="token" type="password" autocomplete="current-password" autofocus>
{error_html}<button type="submit">Sign in</button></form></body></html>"""


def _admin_html() -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Meeting Assistant Admin</title>{_style()}</head>
<body><header><h1>Meeting Assistant</h1><div class="header-actions"><div id="status" aria-live="polite">Loading…</div><a class="button-link" href="/admin/settings">Settings</a></div></header>
<main><section class="grid"><div class="panel history-panel"><div class="history-tools"><div class="manual-join"><label class="sr-only" for="manualMeetCode">Meet code or link</label><input id="manualMeetCode" name="manualMeetCode" placeholder="Paste Meet code or link…" autocomplete="off" autocapitalize="none" spellcheck="false" onpaste="setTimeout(manualJoin,0)" onkeydown="if(event.key==='Enter')manualJoin()"><button onclick="manualJoin()">Join</button></div></div><h2>History</h2><div class="filters"><label class="sr-only" for="searchTitle">Search title</label><input id="searchTitle" name="searchTitle" placeholder="Search title…" autocomplete="off" oninput="renderMeetings(1)"><label class="sr-only" for="dateFrom">From date</label><input id="dateFrom" name="dateFrom" type="date" autocomplete="off" onchange="renderMeetings(1)"><label class="sr-only" for="dateTo">To date</label><input id="dateTo" name="dateTo" type="date" autocomplete="off" onchange="renderMeetings(1)"><button onclick="clearFilters()">Clear</button></div><div id="meetings" class="timeline"></div><div id="pagination" class="pagination"></div></div>
<div class="panel detail"><h2>Meeting Detail</h2><div id="detail" class="empty-detail">Select a meeting.</div></div></section></main>
<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
<script>{_script("dashboard")}</script></body></html>"""


def _settings_html() -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Meeting Assistant Settings</title>{_style()}</head>
<body><header><h1>Settings</h1><div class="header-actions"><div id="status" aria-live="polite">Loading…</div><a class="button-link" href="/admin">Dashboard</a></div></header>
<main><section class="panel settings-panel"><div class="panel-head"><h2>Retention</h2></div><div class="settings-row"><label for="audioRetentionDays">Audio retention days</label><input id="audioRetentionDays" name="audioRetentionDays" type="number" min="0" max="3650" step="1" inputmode="numeric" autocomplete="off"><button onclick="saveRetention()">Save</button><span id="settingsMsg" class="muted" aria-live="polite"></span></div></section></main>
<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
<script>{_script("settings")}</script></body></html>"""


def _style() -> str:
    return """<style>
*{box-sizing:border-box}body{margin:0;background:#070b12;color:#e5e7eb;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;color-scheme:dark;-webkit-tap-highlight-color:transparent}
header{height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 20px;background:#0b1220;color:#f8fafc;border-bottom:1px solid #1f2937}.header-actions,.panel-actions{display:flex;align-items:center;gap:8px}
h1,h2,h3{margin:0} h1{font-size:18px} h2{font-size:15px}
main{padding:18px;display:flex;flex-direction:column;gap:16px}.grid{display:grid;grid-template-columns:minmax(420px,2fr) minmax(520px,3fr);gap:16px}
.panel{background:#0f172a;border:1px solid #263244;border-radius:8px;overflow:hidden;box-shadow:0 14px 40px rgba(0,0,0,.28)}.panel h2,.panel-head{padding:12px 14px;border-bottom:1px solid #263244}.panel-head{display:flex;align-items:center;justify-content:space-between}.history-panel.locked .filters,.history-panel.locked .pagination{pointer-events:none;opacity:.55}
button,input,textarea,.button-link{border:1px solid #334155;background:#182235;color:#e5e7eb;border-radius:6px;touch-action:manipulation}button,input,.button-link{height:32px;padding:0 10px}textarea{width:100%;min-height:96px;padding:10px;resize:vertical;font:inherit;line-height:1.45}button{cursor:pointer}button:hover,.button-link:hover{background:#22304a;border-color:#475569}button.danger{background:#451a1a;border-color:#7f1d1d;color:#fecaca}button.danger:hover{background:#5f1d1d;border-color:#991b1b}button:focus-visible,input:focus-visible,textarea:focus-visible,.button-link:focus-visible{outline:2px solid #38bdf8;outline-offset:2px}.button-link{display:inline-flex;align-items:center;text-decoration:none}input::placeholder,textarea::placeholder{color:#64748b}.history-tools{padding:12px 14px;border-bottom:1px solid #263244}.manual-join{display:grid;grid-template-columns:minmax(180px,1fr) auto;gap:8px;align-items:center;width:min(40%,460px);min-width:320px}.manual-join input{width:100%}.service-status{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:3px 9px;border:1px solid #334155;background:#111827;color:#e5e7eb;font-size:12px;line-height:1.3}.service-status:before{content:"";width:7px;height:7px;border-radius:999px;background:currentColor}.service-status.running{background:#102f20;border-color:#166534;color:#86efac}.service-status.degraded{background:#422006;border-color:#a16207;color:#fde68a}.service-status.failed{background:#451a1a;border-color:#991b1b;color:#fecaca}.service-status.starting{background:#172554;border-color:#1d4ed8;color:#93c5fd}.service-status.idle{background:#1f2937;border-color:#475569;color:#cbd5e1}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.settings-panel{max-width:760px}.settings-row{display:grid;grid-template-columns:180px 120px auto 1fr;gap:10px;align-items:center;padding:12px 14px}.filters{display:grid;grid-template-columns:minmax(0,1fr) minmax(112px,126px) minmax(112px,126px) auto;gap:8px;padding:12px 14px;border-bottom:1px solid #263244}.filters input{min-width:0}.filters input[type=date]{padding:0 6px;font-size:13px}
.timeline{padding:0;position:relative}.timeline.locked{pointer-events:none}.timeline.locked .timeline-row{opacity:.55}.day-group{border-bottom:1px solid #243044}.day-stamp{display:flex;align-items:baseline;gap:8px;padding:9px 16px;background:#0b1220;color:#cbd5e1;border-bottom:1px solid #243044}.day-num{font-size:18px;font-weight:800;line-height:1;color:#f8fafc}.day-label{color:#94a3b8;font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase}.timeline-row{position:relative;display:grid;grid-template-columns:18px minmax(68px,86px) minmax(0,1fr);gap:12px;padding:12px 14px;border-bottom:1px solid #1d2736;cursor:pointer}.timeline-row:last-child{border-bottom:0}.timeline-row:hover,.timeline-row.selected{background:#141d2d}.timeline-row.selected{box-shadow:inset 3px 0 0 #38bdf8}.timeline-row.loading{opacity:1;background:#111c2d}.timeline-row.loading:after{content:"";position:absolute;right:12px;top:50%;width:14px;height:14px;margin-top:-7px;border:2px solid #334155;border-top-color:#38bdf8;border-radius:999px;animation:spin .8s linear infinite}.timeline-dot{width:9px;height:9px;margin-top:5px;border-radius:999px;border:2px solid #38bdf8;background:#38bdf8}.timeline-dot.empty{background:transparent}.timeline-time{color:#d1d5db;font-size:14px;line-height:1.35;white-space:nowrap}.timeline-main{min-width:0}.timeline-title-row,.timeline-meta-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center}.timeline-title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#f3f4f6;font-size:15px;font-weight:700}.timeline-code{justify-self:end}.timeline-meta-row{margin-top:4px}.timeline-range{color:#94a3b8;font-size:11px}.timeline-empty{padding:16px;color:#94a3b8}.detail-loading{min-height:320px;display:grid;place-items:center;color:#cbd5e1}.loader{display:flex;align-items:center;gap:10px}.loader:before{content:"";width:20px;height:20px;border:2px solid #334155;border-top-color:#38bdf8;border-radius:999px;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.meet-code{display:inline-flex;align-items:center;gap:5px;max-width:100%;vertical-align:middle}.meet-code-text{color:#94a3b8;font-size:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}.meet-code-actions{display:inline-flex;align-items:center;gap:3px}.icon-btn{width:24px;height:24px;padding:0;display:inline-flex;align-items:center;justify-content:center;background:transparent;border:1px solid transparent;border-radius:5px;color:#94a3b8;text-decoration:none}.icon-btn:hover{background:#1e293b;border-color:#334155;color:#e5e7eb}.icon-btn svg{width:13px;height:13px}
.pagination{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 14px;border-top:1px solid #263244}.pagination .pager-actions{display:flex;gap:8px}.pagination button:disabled{opacity:.45;cursor:not-allowed}
.muted{color:#94a3b8}.status{display:inline-flex;align-items:center;gap:5px;border-radius:999px;padding:2px 8px;background:#1e293b;color:#c7d2fe;font-size:12px;line-height:1.35}.status:before{content:"";width:7px;height:7px;border-radius:999px;background:currentColor}.status.failed{background:#451a1a;color:#fecaca}.status.delivered{background:#102f20;color:#86efac}.status.no_one_joined,.status.recorded{background:#1f2937;color:#cbd5e1}.status.recording,.status.processing-running{background:#422006;color:#fde68a}.status.processing-done{background:#102f20;color:#86efac}.status.processing-failed{background:#451a1a;color:#fecaca}.status.processing-queued{background:#172554;color:#bfdbfe}.status.scheduled{background:#172554;color:#93c5fd}.status.joining{background:#312e81;color:#c4b5fd}.status.upcoming{background:#0c2d48;color:#7dd3fc}.status.checking{background:#172554;color:#bfdbfe}.status.checking .dots span,.status.processing-running .dots span,.status.processing-queued .dots span{animation:dotPulse 1.2s infinite;opacity:.25}.status.checking .dots span:nth-child(2),.status.processing-running .dots span:nth-child(2),.status.processing-queued .dots span:nth-child(2){animation-delay:.2s}.status.checking .dots span:nth-child(3),.status.processing-running .dots span:nth-child(3),.status.processing-queued .dots span:nth-child(3){animation-delay:.4s}@keyframes dotPulse{0%,80%,100%{opacity:.25}40%{opacity:1}}
.detail{min-height:520px}.empty-detail{padding:14px}.detail-body{padding:14px}.meta-grid{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #1f2937}.kv{display:grid;grid-template-columns:minmax(112px,34%) 1fr;gap:8px;padding:8px 12px 8px 0;border-bottom:1px solid #1f2937;min-width:0}.kv:nth-child(odd){border-right:1px solid #1f2937}.kv.wide{display:block;grid-column:1/-1;border-right:0;padding:12px 0 14px}.kv.wide>.muted{margin-bottom:8px}.kv.wide>div:last-child{width:100%}.kv>div{min-width:0}.instruction-box{margin:12px 0 16px;border:1px solid #263244;border-radius:8px;background:#0b1220;padding:12px;display:flex;flex-direction:column;gap:10px}.instruction-box h3{font-size:13px}.instruction-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.ai-progress{height:8px;background:#111827;border:1px solid #263244;border-radius:999px;overflow:hidden}.ai-progress-fill{height:100%;width:0;background:linear-gradient(90deg,#38bdf8,#22c55e);transition:width .25s ease}.code-block{margin:12px 0 18px;border:1px solid #263244;border-radius:8px;overflow:hidden;background:#050914}.code-head{height:38px;display:flex;align-items:center;justify-content:space-between;padding:0 10px;background:#111827;border-bottom:1px solid #263244}.code-head h3{font-size:13px}.code-actions{display:flex;align-items:center;gap:6px}.copy-btn{width:30px;height:30px;padding:0;display:inline-flex;align-items:center;justify-content:center}.copy-btn svg{width:15px;height:15px}.copied{background:#103224!important;border-color:#166534!important;color:#86efac!important}pre{white-space:pre-wrap;background:#050914;color:#e5e7eb;margin:0;padding:12px;max-height:360px;overflow:auto}
.audio-loader{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.audio-stage.is-hidden{display:none}.continuous-player{display:flex;flex-direction:column;gap:8px;width:100%;max-width:none}.audio-toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.audio-main{min-width:72px}.segments-row{display:flex;flex-wrap:wrap;gap:6px}.segment-chip{height:28px;padding:0 8px;border-radius:999px;font-size:12px;display:inline-flex;align-items:center;gap:5px}.segment-chip span{color:#94a3b8;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10px}.segment-chip.active{background:#0c4a6e;border-color:#0284c7;color:#e0f2fe}.segment-chip.active span{color:#bae6fd}.segment-chip:disabled{opacity:.45;cursor:not-allowed}.progress-bar{width:100%;height:34px;background:#111827;border-radius:8px;cursor:pointer;overflow:hidden;border:1px solid #334155;position:relative}.progress-bar.loading{cursor:wait}.waveform-bg{position:absolute;inset:3px 4px;display:flex;align-items:center;gap:1px;opacity:.7;pointer-events:none}.wave-bar{flex:1;min-width:1px;border-radius:999px;background:#475569;opacity:.22}.wave-bar.loaded{background:#7dd3fc;opacity:.65}.load-fill{position:absolute;left:0;top:0;bottom:0;width:0;background:rgba(148,163,184,.12);pointer-events:none}.progress-fill{position:absolute;left:0;top:0;bottom:0;width:0;background:linear-gradient(90deg,rgba(56,189,248,.28),rgba(56,189,248,.08));border-right:2px solid #38bdf8;pointer-events:none}.rate-btns{display:flex;gap:4px}.rate-btn{height:26px;padding:0 7px;font-size:12px}.rate-btn.active{background:#0c4a6e;border-color:#0284c7;color:#e0f2fe}.audio-note{font-size:12px}.login{min-height:100vh;display:grid;place-items:center;background:#070b12}.login-box{width:min(360px,calc(100vw - 32px));background:#0f172a;border:1px solid #263244;border-radius:8px;padding:20px;display:flex;flex-direction:column;gap:10px}.login-box input{height:36px;border:1px solid #334155;background:#070b12;color:#e5e7eb;border-radius:6px;padding:0 10px}.error{color:#fca5a5;margin:0}audio{width:100%;height:34px}
@media(max-width:900px){.grid{grid-template-columns:1fr}.filters,.settings-row,.manual-join{grid-template-columns:1fr 1fr}.manual-join{width:100%;min-width:0}.manual-join input{grid-column:1/-1}.settings-row label{grid-column:1/-1}.timeline-row{grid-template-columns:16px 74px minmax(0,1fr);gap:10px;padding:11px 10px}.timeline-time{font-size:13px}.timeline-title{font-size:15px}.timeline-title-row,.timeline-meta-row{grid-template-columns:1fr}.timeline-code{justify-self:start}.meet-code{flex-wrap:wrap}.meet-code-text{white-space:normal;overflow-wrap:anywhere}.meta-grid{grid-template-columns:1fr}.kv{grid-column:auto;grid-template-columns:132px 1fr;border-right:0;padding-right:0}.kv.wide{display:block;grid-column:auto;border-right:0;padding-right:0}}
</style>"""


def _script(page: str = "dashboard") -> str:
    boot = "loadDashboard(); setInterval(loadStatus,15000);" if page == "dashboard" else "loadSettingsPage(); setInterval(loadStatus,15000);"
    return r"""
async function api(path, opts={}){const r=await fetch('/admin/api/'+path,{cache:'no-store',...opts}); if(!r.ok) throw new Error(await r.text()); return r.json();}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmt(v){if(!v)return ''; if(/^\d{4}-\d{2}-\d{2}$/.test(String(v)))return v; try{const d=new Date(v); return `${d.toLocaleTimeString([], {hour:'numeric',minute:'2-digit',second:'2-digit'})} · ${d.toLocaleDateString()}`;}catch{return v;}}
function badge(status){const labels={delivered:'Done',failed:'Fail',scheduled:'Sched',joining:'Join',recording:'Rec',recorded:'Saved',processing:'Proc',no_one_joined:'Empty',cancelled:'Cancel'}; return `<span class="status ${esc(status)}">${esc(labels[status]||status)}</span>`}
function processingBadge(m){const state=String(m.processing_status||''); if(!state||state==='idle')return ''; const total=Number(m.processing_total||0); const batch=Number(m.processing_batch||0); const stage=String(m.processing_stage||'AI'); if(state==='queued')return `<span class="status processing-queued">AI Queued<span class="dots"><span>.</span><span>.</span><span>.</span></span></span>`; if(state==='running')return `<span class="status processing-running">${esc(stage)} ${batch||0}/${total||'?'}<span class="dots"><span>.</span><span>.</span><span>.</span></span></span>`; if(state==='done')return `<span class="status processing-done">AI Done</span>`; if(state==='failed')return `<span class="status processing-failed">AI Fail</span>`; return `<span class="status">${esc(state)}</span>`;}
function processingLine(m){const badgeHtml=processingBadge(m); if(!badgeHtml)return 'idle'; const stage=m.processing_stage?` <span class="muted">${esc(m.processing_stage)}</span>`:''; const err=m.processing_error?` <span class="muted">${esc(m.processing_error)}</span>`:''; return badgeHtml+stage+err+processingProgress(m);}
function processingProgress(m){const state=String(m.processing_status||''); if(!['queued','running'].includes(state))return ''; const total=Number(m.processing_total||0); const batch=Number(m.processing_batch||0); const pct=total?Math.max(4,Math.min(100,Math.round((batch/total)*100))):4; return `<div class="ai-progress" title="${pct}%"><div class="ai-progress-fill" style="width:${pct}%"></div></div>`;}
function checkingBadge(){return `<span class="status checking">Checking<span class="dots"><span>.</span><span>.</span><span>.</span></span></span>`}
let allMeetings=[];
const urlState=new URLSearchParams(window.location.search);
let selectedMeeting=urlState.get('meeting')||'';
let currentPage=Number(urlState.get('page')||'1')||1;
let detailPollTimer=null;
let watchedMeeting='';
let pendingAction=null;
let manualJoinBusy=false;
let detailLoadingCode='';
const audioMetaCache=new Map();
const pageSize=20;
async function loadAll(){await loadDashboard();}
async function loadDashboard(){await Promise.all([loadStatus(),loadMeetings()]); if(selectedMeeting) await loadDetail(selectedMeeting,{push:false});}
async function loadSettingsPage(){await Promise.all([loadStatus(),loadSettings()]);}
async function loadStatus(){const d=await api('status'); const el=document.getElementById('status'); const state=String(d.state||'idle'); const labels={running:'Run',starting:'Boot',degraded:'Warn',failed:'Fail',idle:'Idle'}; el.className=`service-status ${esc(state)}`; el.title=[state,d.detail].filter(Boolean).join(': '); el.textContent=labels[state]||state.slice(0,4);}
async function loadSettings(){const d=await api('settings'); document.getElementById('audioRetentionDays').value=d.settings.audio_retention_days;}
async function saveRetention(){const days=Number(document.getElementById('audioRetentionDays').value); const msg=document.getElementById('settingsMsg'); const d=await api('settings/audio-retention',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({audio_retention_days:days})}); msg.textContent=`saved: ${d.settings.audio_retention_days} days`; setTimeout(()=>msg.textContent='',1600);}
async function loadMeetings(){const d=await api('meetings'); allMeetings=d.meetings; renderMeetings(currentPage,{push:false});}
function filteredMeetings(){const q=document.getElementById('searchTitle')?.value.trim().toLowerCase()||''; const from=document.getElementById('dateFrom')?.value||''; const to=document.getElementById('dateTo')?.value||''; return allMeetings.filter(m=>{const title=String(m.title||'').toLowerCase(); const day=localDateKey(m.scheduled_start_utc); return (!q||title.includes(q))&&(!from||day>=from)&&(!to||day<=to);});}
function updateUrl({code=selectedMeeting,page=currentPage,mode='push'}={}){const params=new URLSearchParams(window.location.search); if(code)params.set('meeting',code); else params.delete('meeting'); if(page&&page>1)params.set('page',String(page)); else params.delete('page'); const qs=params.toString(); const next=window.location.pathname+(qs?`?${qs}`:''); if(next!==window.location.pathname+window.location.search)history[mode==='replace'?'replaceState':'pushState']({},'',next);}
function renderMeetings(page=currentPage,{push=true}={}){const rows=filteredMeetings(); const totalPages=Math.max(1,Math.ceil(rows.length/pageSize)); currentPage=Math.min(Math.max(1,page),totalPages); const start=(currentPage-1)*pageSize; const pageRows=rows.slice(start,start+pageSize); const el=document.getElementById('meetings'); const locked=!!detailLoadingCode; el.classList.toggle('locked',locked); el.closest('.history-panel')?.classList.toggle('locked',locked); el.innerHTML=timelineHtml(pageRows); renderPagination(rows.length,totalPages); if(push)updateUrl({page:currentPage,mode:'replace'});}
function timelineHtml(rows){if(!rows.length)return '<div class="timeline-empty">No meetings.</div>'; const groups=new Map(); for(const m of rows){const key=localDateKey(m.scheduled_start_utc)||'undated'; if(!groups.has(key))groups.set(key,[]); groups.get(key).push(m);} return [...groups.entries()].map(([day,items])=>`<section class="day-group"><div class="day-stamp">${dayStamp(day)}</div><div class="day-items">${items.map(timelineRow).join('')}</div></section>`).join('');}
function timelineRow(m){const code=esc(m.meet_code); const classes=['timeline-row']; if(m.meet_code===selectedMeeting)classes.push('selected'); if(m.meet_code===detailLoadingCode)classes.push('loading'); return `<div class="${classes.join(' ')}" onclick="selectMeeting('${code}')"><div class="timeline-dot ${isActiveStatus(m.status)?'':'empty'}"></div><div class="timeline-time">${timeRange(m)}</div><div class="timeline-main"><div class="timeline-title-row"><div class="timeline-title">${esc(m.title)}</div><span>${badge(m.status)}${processingBadge(m)}</span></div><div class="timeline-meta-row"><div class="timeline-range">${dateTimeRange(m)}</div><div class="timeline-code">${meetCodeTools(m.meet_code)}</div></div></div></div>`;}
function selectMeeting(code){if(detailLoadingCode)return; loadDetail(code);}
function renderPagination(total,totalPages){const el=document.getElementById('pagination'); if(!el)return; const start=total?((currentPage-1)*pageSize+1):0; const end=Math.min(currentPage*pageSize,total); el.innerHTML=`<span class="muted">${start}-${end} of ${total}</span><div class="pager-actions"><button onclick="renderMeetings(${currentPage-1})" ${currentPage<=1?'disabled':''}>Prev</button><button onclick="renderMeetings(${currentPage+1})" ${currentPage>=totalPages?'disabled':''}>Next</button></div>`;}
function clearFilters(){document.getElementById('searchTitle').value=''; document.getElementById('dateFrom').value=''; document.getElementById('dateTo').value=''; renderMeetings(1);}
function localDateKey(v){if(!v)return ''; const d=new Date(v); if(Number.isNaN(d.getTime()))return ''; const m=String(d.getMonth()+1).padStart(2,'0'); const day=String(d.getDate()).padStart(2,'0'); return `${d.getFullYear()}-${m}-${day}`;}
function dayStamp(key){if(!key||key==='undated')return '<span class="day-num">--</span><span class="day-label">No date</span>'; const d=new Date(`${key}T00:00:00`); const day=String(d.getDate()); const label=d.toLocaleDateString([], {month:'short', weekday:'short'}).replace(',', ''); return `<span class="day-num">${day}</span><span class="day-label">${esc(label)}</span>`;}
function timeRange(m){const start=timeText(m.scheduled_start_utc); const end=timeText(m.scheduled_end_utc); if(start&&end)return `${start}<br>${end}`; return start||'--';}
function dateTimeRange(m){const start=fmt(m.scheduled_start_utc); const end=m.scheduled_end_utc?timeText(m.scheduled_end_utc):''; return end?`${start} - ${end}`:start;}
function timeText(v){if(!v)return ''; try{return new Date(v).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}).replace(' ', '').toLowerCase();}catch{return '';}}
function normalizeMeetCode(value){const match=String(value||'').trim().toLowerCase().match(/([a-z]{3})-?([a-z]{4})-?([a-z]{3})/); return match?`${match[1]}-${match[2]}-${match[3]}`:'';}
async function loadDetail(code,{push=true,lock=true}={}){selectedMeeting=code; if(push)updateUrl({code,page:currentPage}); if(lock){detailLoadingCode=code; renderMeetings(currentPage,{push:false}); document.getElementById('detail').innerHTML=`<div class="detail-loading"><div class="loader">Loading meeting detail...</div></div>`;} try{const d=await api('meetings/'+encodeURIComponent(code)); const m=d.meeting; const files=m.files||{}; if(pendingAction?.code===code&&m.status!==pendingAction.fromStatus)pendingAction=null; const statusHtml=pendingAction?.code===code?checkingBadge():badge(m.status); if(lock)detailLoadingCode=''; renderMeetings(currentPage,{push:false}); document.getElementById('detail').innerHTML=`<div class="detail-body"><h3>${esc(m.title)}</h3><p>${actionButtons(m)}</p>
<div class="meta-grid">${kv('Status',statusHtml)}${kv('AI processing',processingLine(m))}${kv('Meeting ended',meetingEndedLine(m))}${kv('Meet code',meetCodeTools(m.meet_code))}${kv('Event ID',esc(m.event_id))}${kv('Host',esc(m.organizer||''))}${kv('Attendees',attendeeList(m.attendees))}${kv('Start',fmt(m.scheduled_start_utc))}${kv('End',fmt(m.scheduled_end_utc))}${kv('Actual meet end',fmt(m.actual_end_utc))}${kv('Delivered',fmt(m.delivered_at))}${m.last_error?kv('Error',esc(m.last_error)):''}</div>${kv('Listen',audioPlayer(m),'wide')}
${instructionBox(m)}${codeBlock('Meeting Minutes',files.minutes?.content||'',{pdf:true,optional:true})}${codeBlock('Summary',files.summary?.content||'',{optional:true})}${codeBlock('Transcript',files.transcript?.content||'')}${codeBlock('Notes',files.notes?.content||'',{optional:true})}</div>`; initAudioPlayers();}catch(e){if(lock){detailLoadingCode=''; renderMeetings(currentPage,{push:false});} document.getElementById('detail').innerHTML=`<div class="empty-detail error">Failed to load meeting: ${esc(e.message||String(e))}</div>`; throw e;}}
function actionButtons(m){const rejoin=`<button onclick="rejoin('${esc(m.meet_code)}')">Rejoin</button>`; const out=m.status==='recording'?` <button class="danger" onclick="forceOut('${esc(m.meet_code)}')">Out</button>`:''; return rejoin+out;}
function swalOptions(extra){return {background:'#0f172a',color:'#e5e7eb',confirmButtonColor:'#2563eb',cancelButtonColor:'#475569',...extra};}
async function notify(icon,title,text=''){if(window.Swal){await Swal.fire(swalOptions({icon,title,text,toast:true,position:'top-end',timer:1800,showConfirmButton:false,timerProgressBar:true}));return;} console[icon==='error'?'error':'log']([title,text].filter(Boolean).join(' '));}
async function confirmDialog(title,text,confirmButtonText='Confirm'){if(window.Swal){const r=await Swal.fire(swalOptions({icon:'warning',title,text,showCancelButton:true,confirmButtonText,cancelButtonText:'Cancel',confirmButtonColor:'#dc2626'}));return r.isConfirmed;} console.warn([title,text].filter(Boolean).join(' ')); return false;}
function isActiveStatus(status){return ['scheduled','joining','recording'].includes(String(status||''));}
function isBusyProcessing(m){return ['queued','running'].includes(String(m?.processing_status||''));}
function stopDetailPolling(){if(detailPollTimer){clearInterval(detailPollTimer); detailPollTimer=null;} watchedMeeting='';}
function startDetailPolling(code){watchedMeeting=code; if(detailPollTimer)clearInterval(detailPollTimer); detailPollTimer=setInterval(async()=>{if(!watchedMeeting)return; await loadMeetings(); const row=allMeetings.find(m=>m.meet_code===watchedMeeting); if(row&&pendingAction?.code===watchedMeeting&&(row.status!==pendingAction.fromStatus||isBusyProcessing(row)))pendingAction=null; await loadDetail(watchedMeeting,{push:false,lock:false}); if(row&&!isActiveStatus(row.status)&&!isBusyProcessing(row)&&!pendingAction)stopDetailPolling();},3000);}
async function queueAction(code,path,successText){const current=allMeetings.find(m=>m.meet_code===code); pendingAction={code,fromStatus:current?.status||''}; await loadDetail(code,{push:false}); startDetailPolling(code); try{const result=await api('meetings/'+encodeURIComponent(code)+'/'+path,{method:'POST'}); if(result.error){throw new Error(result.error);} await notify('success',successText);}catch(e){pendingAction=null; stopDetailPolling(); await loadDetail(code,{push:false}); await notify('error','Action failed',e.message||String(e));}}
async function rejoin(code){await queueAction(code,'rejoin','Rejoin queued');}
async function forceOut(code){const ok=await confirmDialog('Force bot out?', 'Bot will leave Meet and process transcript now.', 'Out'); if(!ok)return; await queueAction(code,'force-out','Out queued');}
async function regenerate(code){const instruction=(document.getElementById('adminInstruction')?.value||'').trim(); if(!instruction){await notify('error','Instruction required','Add meeting-minutes instruction before generating.'); return;} const ok=await confirmDialog('Generate meeting minutes?', 'Minutes, summary, and notes will be generated from the saved transcript using your instruction.', 'Generate'); if(!ok)return; pendingAction={code,fromStatus:''}; startDetailPolling(code); try{const result=await api('meetings/'+encodeURIComponent(code)+'/regenerate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({admin_instruction:instruction})}); if(result.error)throw new Error(result.error); await loadDetail(code,{push:false,lock:false}); await notify('success','Generation queued',code);}catch(e){pendingAction=null; stopDetailPolling(); await notify('error','Generation failed',e.message||String(e));}}
async function manualJoin(){if(manualJoinBusy)return; const input=document.getElementById('manualMeetCode'); const code=normalizeMeetCode(input?.value||''); if(!code){await notify('error','Invalid Meet code','Paste a Google Meet code or URL.'); return;} manualJoinBusy=true; pendingAction={code,fromStatus:''}; selectedMeeting=code; updateUrl({code,page:currentPage}); document.getElementById('detail').innerHTML=`<div class="detail-body"><h3>${meetCodeTools(code)}</h3>${kv('Status',checkingBadge())}</div>`; try{const result=await api('manual-join',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({meet_code:code})}); if(result.error){throw new Error(result.error);} input.value=result.meet_code; pendingAction={code:result.meet_code,fromStatus:result.meeting?.status||''}; await loadMeetings(); await loadDetail(result.meet_code,{push:true}); startDetailPolling(result.meet_code); await notify('success','Join queued',result.meet_code);}catch(e){pendingAction=null; await notify('error','Join failed',e.message||String(e));}finally{manualJoinBusy=false;}}
window.addEventListener('popstate',async()=>{const params=new URLSearchParams(window.location.search); selectedMeeting=params.get('meeting')||''; currentPage=Number(params.get('page')||'1')||1; renderMeetings(currentPage,{push:false}); if(selectedMeeting)await loadDetail(selectedMeeting,{push:false}); else document.getElementById('detail').innerHTML='Select a meeting.';});
function kv(k,v,cls=''){return `<div class="kv ${esc(cls)}"><div class="muted">${k}</div><div>${v}</div></div>`}
function meetingEndedLine(m){const ok=!!m.meeting_end_confirmed; const status=`<span class="status ${ok?'delivered':'failed'}">${ok?'Yes':'No'}</span>`; const reason=m.meeting_end_reason?` <span class="muted">${esc(m.meeting_end_reason)}</span>`:''; return status+reason;}
function instructionBox(m){return `<section class="instruction-box"><h3>Meeting minutes instruction</h3><textarea id="adminInstruction" placeholder="Required. Add speaker mapping, terms, format, and what to emphasize before generating minutes...">${esc(m.admin_instruction||'')}</textarea>${processingProgress(m)}<div class="instruction-actions"><button onclick="regenerate('${esc(m.meet_code)}')">Generate minutes</button><span class="muted">Default output is transcript only. Minutes are generated only after instruction.</span></div></section>`;}
function meetCodeTools(code){if(!code)return 'missing'; const safe=esc(code); const href=`https://meet.google.com/${encodeURIComponent(code)}`; return `<span class="meet-code"><span class="meet-code-text">${safe}</span><span class="meet-code-actions"><button class="icon-btn" onclick="event.stopPropagation();copyText('${safe}',this)" title="Copy Meet code" aria-label="Copy Meet code">${copyIcon()}</button><a class="icon-btn" onclick="event.stopPropagation()" href="${href}" target="_blank" rel="noopener noreferrer" title="Open Meet" aria-label="Open Meet">${linkIcon()}</a></span></span>`;}
function copyIcon(){return `<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>`;}
function linkIcon(){return `<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.07 0l3.54-3.54a5 5 0 0 0-7.07-7.07L11.5 4.43"></path><path d="M14 11a5 5 0 0 0-7.07 0L3.39 14.54a5 5 0 0 0 7.07 7.07l2.04-2.04"></path></svg>`;}
function attendeeList(v){if(Array.isArray(v)&&v.length)return v.map(esc).join('<br>'); return 'missing';}
function fileLine(f){return f?.exists?`${esc(f.path)} <span class="muted">(${f.size} bytes)</span>`:'missing'}
let continuousPlayer=null;
function audioPlayer(m){const segments=(m.files?.audio_segments||[]).filter(f=>f?.exists&&f?.size>0&&f?.duration_seconds>0); if(!segments.length)return 'missing'; const total=segments[segments.length-1]?.end_second||0; const count=segments.length; return `<div class="continuous-player" data-meet-code="${esc(m.meet_code)}" data-count="${count}" data-total="${total}"><div class="audio-loader"><button id="loadAudioBtn" onclick="loadAudioMeta()">Load audio</button><span id="audioLoadStatus" class="muted">${count} segment${count>1?'s':''} · ${formatDuration(total)}</span></div><div id="audioStage" class="audio-stage is-hidden"><div class="audio-toolbar"><button class="audio-main" onclick="toggleContinuousAudio()" disabled>Play</button><span id="audioNow" class="muted">Segment 1 / ${count}</span><span id="audioTime" class="muted">0:00 / ${formatDuration(total)}</span><div class="rate-btns"><button class="rate-btn active" onclick="setPlaybackRate(1,this)">x1</button><button class="rate-btn" onclick="setPlaybackRate(2,this)">x2</button><button class="rate-btn" onclick="setPlaybackRate(4,this)">x4</button></div></div><audio id="continuousAudio" preload="none"></audio><div class="progress-bar loading" onclick="onAudioProgressClick(event)" role="slider" tabindex="0" aria-label="Seek"><div id="waveformBg" class="waveform-bg"></div><div id="audioLoadProgress" class="load-fill"></div><div id="audioProgress" class="progress-fill"></div></div><div id="segmentsRow" class="segments-row"></div><div class="audio-note muted">Audio and waveform load only after this button. Segments preload sequentially after segment 1 is ready.</div></div></div>`;}
function initAudioPlayers(){continuousPlayer=null; const root=document.querySelector('.continuous-player'); if(!root)return; continuousPlayer={root,meetCode:root.dataset.meetCode,segments:[],index:0,rate:1,loaded:new Set(),preloading:false,audio:null};}
async function loadAudioMeta(){if(!continuousPlayer||continuousPlayer.preloading)return; const btn=document.getElementById('loadAudioBtn'); const status=document.getElementById('audioLoadStatus'); btn.disabled=true; btn.textContent='Loading...'; if(status)status.textContent='Loading waveform...'; try{let segments=audioMetaCache.get(continuousPlayer.meetCode); if(!segments){const d=await api('meetings/'+encodeURIComponent(continuousPlayer.meetCode)+'/audio-meta'); segments=(d.audio_segments||[]).filter(f=>f?.exists&&f?.size>0&&f?.duration_seconds>0); audioMetaCache.set(continuousPlayer.meetCode,segments);} if(!segments.length)throw new Error('No audio segments'); continuousPlayer.segments=segments.map((s,i)=>({index:i,sourceIndex:s.index??i,start_second:s.start_second??0,end_second:s.end_second??0,duration_seconds:s.duration_seconds??0,size:s.size??0,peaks:s.peaks||[]})); document.getElementById('audioStage')?.classList.remove('is-hidden'); renderAudioControls(); renderWaveform(); setupContinuousAudio(); await loadSegment(0,0,false); preloadSegmentsSequential(1);}catch(e){btn.disabled=false; btn.textContent='Load audio'; if(status)status.textContent=e.message||String(e); await notify('error','Audio load failed',e.message||String(e));}}
function renderAudioControls(){const row=document.getElementById('segmentsRow'); if(!row||!continuousPlayer)return; row.innerHTML=continuousPlayer.segments.map((f,i)=>`<button class="segment-chip" data-index="${i}" onclick="loadSegment(${i},0,true)" disabled title="Waiting for preload">S${i+1}<span>${formatDuration(f.duration_seconds||0)}</span></button>`).join('');}
function setupContinuousAudio(){const audio=document.getElementById('continuousAudio'); continuousPlayer.audio=audio; audio.addEventListener('loadedmetadata',updateAudioTime); audio.addEventListener('timeupdate',updateAudioTime); audio.addEventListener('play',()=>setAudioButton(true)); audio.addEventListener('pause',()=>setAudioButton(false)); audio.addEventListener('ended',()=>{if(!continuousPlayer)return; const next=continuousPlayer.index+1; if(next<continuousPlayer.segments.length){loadSegment(next,0,true);}else{setAudioButton(false);}});}
function renderWaveform(){const target=document.getElementById('waveformBg'); if(!target||!continuousPlayer)return; const bars=[]; const segments=continuousPlayer.segments; const total=segments.at(-1)?.end_second||0; for(const segment of segments){const duration=segment.duration_seconds||Math.max(1,(segment.end_second||0)-(segment.start_second||0)); const peaks=(segment.peaks&&segment.peaks.length?segment.peaks:[8]); const weight=Math.max(1,Math.round((duration/Math.max(1,total))*180)); const step=Math.max(1,Math.floor(peaks.length/weight)); for(let i=0;i<peaks.length;i+=step){const height=Math.max(6,Math.min(100,peaks[i]||4)); bars.push(`<span class="wave-bar ${continuousPlayer.loaded.has(segment.index)?'loaded':''}" data-segment="${segment.index}" style="height:${height}%"></span>`);} bars.push(`<span class="wave-bar ${continuousPlayer.loaded.has(segment.index)?'loaded':''}" data-segment="${segment.index}" style="height:8%;opacity:.25"></span>`);} target.innerHTML=bars.join(''); updateLoadProgress();}
function markSegmentLoaded(index){if(!continuousPlayer)return; continuousPlayer.loaded.add(index); document.querySelectorAll(`.wave-bar[data-segment="${index}"]`).forEach(el=>el.classList.add('loaded')); const chip=document.querySelector(`.segment-chip[data-index="${index}"]`); if(chip){chip.disabled=false; chip.title='';} const main=document.querySelector('.audio-main'); if(main&&continuousPlayer.loaded.has(0))main.disabled=false; updateLoadProgress();}
function updateLoadProgress(){if(!continuousPlayer)return; const total=continuousPlayer.segments.length||1; const fill=document.getElementById('audioLoadProgress'); if(fill)fill.style.width=`${Math.round((continuousPlayer.loaded.size/total)*100)}%`; const bar=document.querySelector('.progress-bar'); if(bar)bar.classList.toggle('loading',continuousPlayer.loaded.size<total); const status=document.getElementById('audioLoadStatus'); if(status){const done=continuousPlayer.loaded.size; status.textContent=done<total?`Loaded ${done}/${total} segments`:`Loaded ${total}/${total} segments`;}}
function audioSrc(segment){return `/admin/api/meetings/${encodeURIComponent(continuousPlayer.meetCode)}/audio?index=${segment.sourceIndex}`;}
function preloadAudioSegment(index){if(!continuousPlayer)return Promise.resolve(); const segment=continuousPlayer.segments[index]; if(!segment||continuousPlayer.loaded.has(index))return Promise.resolve(); return new Promise(resolve=>{const audio=new Audio(); const done=()=>{markSegmentLoaded(index); cleanup(); resolve();}; const cleanup=()=>{audio.onloadedmetadata=null; audio.oncanplaythrough=null; audio.onerror=null;}; audio.preload='auto'; audio.onloadedmetadata=done; audio.oncanplaythrough=done; audio.onerror=()=>{cleanup(); resolve();}; audio.src=audioSrc(segment); audio.load();});}
async function preloadSegmentsSequential(start=0){if(!continuousPlayer)return; continuousPlayer.preloading=true; for(let i=start;i<continuousPlayer.segments.length;i++){await preloadAudioSegment(i);} continuousPlayer.preloading=false;}
async function loadSegment(index,offsetSec=0,autoPlay=false){if(!continuousPlayer)return; const segment=continuousPlayer.segments[index]; if(!segment)return; if(!continuousPlayer.loaded.has(index))await preloadAudioSegment(index); const audio=continuousPlayer.audio; continuousPlayer.index=index; audio.src=audioSrc(segment); audio.load(); audio.playbackRate=continuousPlayer.rate||1; audio.onloadedmetadata=()=>{markSegmentLoaded(index); audio.currentTime=Math.max(0,Math.min(offsetSec,Math.max(0,(audio.duration||segment.duration_seconds)-0.1))); updateAudioTime(); if(autoPlay)audio.play().catch(e=>notify('error','Audio failed',e.message||String(e)));}; document.querySelectorAll('.segment-chip').forEach((b,i)=>b.classList.toggle('active',i===index)); const now=document.getElementById('audioNow'); if(now)now.textContent=`Segment ${index+1} / ${continuousPlayer.segments.length}`; updateAudioTime();}
function seekToAudio(absSeconds,autoPlay=true){if(!continuousPlayer||!continuousPlayer.segments.length)return; const first=continuousPlayer.segments[0]; const last=continuousPlayer.segments[continuousPlayer.segments.length-1]; const clamped=Math.min(Math.max(absSeconds,first.start_second),Math.max(first.start_second,last.end_second-0.1)); const idx=continuousPlayer.segments.findIndex(s=>clamped>=s.start_second&&clamped<s.end_second); if(idx>=0)loadSegment(idx,clamped-continuousPlayer.segments[idx].start_second,autoPlay);}
function onAudioProgressClick(event){if(!continuousPlayer?.segments.length)return; const bar=event.currentTarget; const rect=bar.getBoundingClientRect(); const ratio=Math.min(1,Math.max(0,(event.clientX-rect.left)/rect.width)); const first=continuousPlayer.segments[0]; const last=continuousPlayer.segments[continuousPlayer.segments.length-1]; seekToAudio(first.start_second+ratio*(last.end_second-first.start_second),!continuousPlayer.audio.paused);}
async function toggleContinuousAudio(){if(!continuousPlayer)return; if(continuousPlayer.audio.paused){try{await continuousPlayer.audio.play();}catch(e){await notify('error','Audio failed',e.message||String(e));}}else{continuousPlayer.audio.pause();}}
function setPlaybackRate(rate,button){if(!continuousPlayer)return; continuousPlayer.rate=rate; continuousPlayer.audio.playbackRate=rate; document.querySelectorAll('.rate-btn').forEach(btn=>btn.classList.toggle('active',btn===button));}
function setAudioButton(playing){const button=document.querySelector('.audio-main'); if(button)button.textContent=playing?'Pause':'Play';}
function updateAudioTime(){if(!continuousPlayer)return; const audio=continuousPlayer.audio; const segment=continuousPlayer.segments[continuousPlayer.index]||{start_second:0}; const abs=(segment.start_second||0)+(audio.currentTime||0); const total=continuousPlayer.segments.at(-1)?.end_second||0; const el=document.getElementById('audioTime'); if(el)el.textContent=`${formatDuration(abs)} / ${formatDuration(total)}`; const progress=document.getElementById('audioProgress'); if(progress&&total>0){progress.style.width=`${Math.min(100,Math.max(0,(abs/total)*100))}%`;}}
function formatDuration(seconds){seconds=Math.max(0,Math.round(seconds||0)); const h=Math.floor(seconds/3600); const m=Math.floor((seconds%3600)/60); const s=String(seconds%60).padStart(2,'0'); return h?`${h}:${String(m).padStart(2,'0')}:${s}`:`${m}:${s}`;}
function codeBlock(title,content,options={}){if(options.optional&&!String(content||'').trim())return ''; const id='code_'+Math.random().toString(36).slice(2); const pdf=options.pdf?`<button class="copy-btn" onclick="downloadPdf('${id}','${esc(title)}')" title="Download PDF" aria-label="Download PDF">${downloadIcon()}</button>`:''; return `<section class="code-block"><div class="code-head"><h3>${esc(title)}</h3><div class="code-actions">${pdf}<button class="copy-btn" onclick="copyCode('${id}',this)" title="Copy all" aria-label="Copy all">${copyIcon()}</button></div></div><pre id="${id}">${esc(content)}</pre></section>`}
function downloadIcon(){return `<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><path d="M7 10l5 5 5-5"></path><path d="M12 15V3"></path></svg>`;}
function downloadPdf(id,title){const markdown=document.getElementById(id)?.textContent||''; const win=window.open('','_blank'); if(!win){notify('error','Popup blocked','Allow popups to export PDF.');return;} const html=markdownToHtml(markdown); win.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title><style>${pdfCss()}</style></head><body><main class="doc"><header class="doc-head"><p class="eyebrow">Meeting Assistant</p><h1>${esc(title)}</h1><p class="generated">Generated ${new Date().toLocaleString()}</p></header><article>${html}</article></main><script>window.onload=()=>{setTimeout(()=>window.print(),120)}<\/script></body></html>`); win.document.close();}
function markdownToHtml(markdown){const lines=String(markdown||'').replace(/\r\n/g,'\n').split('\n'); let html=''; let list=null; let inCode=false; let code=[]; const closeList=()=>{if(list){html+=`</${list}>`;list=null;}}; const inline=(s)=>esc(s).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>'); const flushCode=()=>{html+=`<pre><code>${esc(code.join('\n'))}</code></pre>`;code=[];}; for(const raw of lines){const line=raw.trimEnd(); if(line.trim().startsWith('```')){if(inCode){flushCode();inCode=false;}else{closeList();inCode=true;} continue;} if(inCode){code.push(raw);continue;} if(!line.trim()){closeList();continue;} const heading=line.match(/^(#{1,4})\s+(.+)$/); if(heading){closeList(); const level=Math.min(4,heading[1].length+1); html+=`<h${level}>${inline(heading[2])}</h${level}>`; continue;} const checked=line.match(/^[-*]\s+\[( |x|X)\]\s+(.+)$/); if(checked){if(list!=='ul'){closeList();html+='<ul class="tasks">';list='ul';} const done=checked[1].toLowerCase()==='x'; html+=`<li class="task ${done?'done':''}"><span class="box">${done?'✓':''}</span><span>${inline(checked[2])}</span></li>`; continue;} const bullet=line.match(/^[-*]\s+(.+)$/); if(bullet){if(list!=='ul'){closeList();html+='<ul>';list='ul';} html+=`<li>${inline(bullet[1])}</li>`; continue;} const numbered=line.match(/^\d+\.\s+(.+)$/); if(numbered){if(list!=='ol'){closeList();html+='<ol>';list='ol';} html+=`<li>${inline(numbered[1])}</li>`; continue;} if(line.includes('|')&&line.replace(/\\|/g,'').trim()){closeList(); html+=`<p class="table-line">${inline(line)}</p>`; continue;} closeList(); html+=`<p>${inline(line)}</p>`;} closeList(); if(inCode)flushCode(); return html||'<p>No content</p>';}
function pdfCss(){return `@page{size:A4;margin:18mm}*{box-sizing:border-box}body{margin:0;background:#f8fafc;color:#111827;font-family:Inter,Arial,sans-serif;font-size:12px;line-height:1.55}.doc{max-width:780px;margin:0 auto;background:#fff;padding:28px 34px}.doc-head{border-bottom:2px solid #0f172a;margin-bottom:22px;padding-bottom:14px}.eyebrow{margin:0 0 4px;color:#2563eb;font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}.generated{margin:4px 0 0;color:#64748b;font-size:10px}h1{margin:0;color:#0f172a;font-size:26px;line-height:1.15}h2{margin:22px 0 8px;color:#0f172a;font-size:17px;border-bottom:1px solid #cbd5e1;padding-bottom:5px}h3{margin:16px 0 6px;color:#1e293b;font-size:14px}h4,h5{margin:12px 0 5px;color:#334155;font-size:12px}p{margin:7px 0}ul,ol{margin:6px 0 10px 20px;padding:0}li{margin:4px 0}strong{color:#0f172a}code{background:#e2e8f0;border:1px solid #cbd5e1;border-radius:4px;padding:1px 4px;font-family:Menlo,Consolas,monospace;font-size:11px}pre{white-space:pre-wrap;background:#0f172a;color:#e5e7eb;border-radius:8px;padding:12px;overflow-wrap:anywhere}.tasks{list-style:none;margin-left:0}.task{display:flex;gap:8px;align-items:flex-start}.box{display:inline-flex;width:13px;height:13px;border:1.5px solid #2563eb;border-radius:3px;align-items:center;justify-content:center;color:#2563eb;font-size:10px;line-height:1;margin-top:3px;flex:0 0 auto}.task.done span:last-child{text-decoration:line-through;color:#64748b}.table-line{font-family:Menlo,Consolas,monospace;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;padding:6px 8px}@media print{body{background:#fff}.doc{padding:0;max-width:none}a{color:inherit}}`;}
async function flashCopied(button){button.classList.add('copied'); setTimeout(()=>button.classList.remove('copied'),900);}
async function copyCode(id,button){const text=document.getElementById(id)?.textContent||''; await navigator.clipboard.writeText(text); flashCopied(button);}
async function copyText(text,button){await navigator.clipboard.writeText(text); flashCopied(button);}
""" + boot + "\n"


def serve_forever() -> None:
    host = os.getenv("HEALTH_HOST", "0.0.0.0")
    port = int(os.getenv("HEALTH_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), AdminHandler)
    server.serve_forever()
