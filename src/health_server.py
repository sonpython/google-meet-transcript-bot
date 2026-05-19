import json
import os
from datetime import UTC, datetime
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from src.auth.oauth_user import OAuthUserAuth
from src.auth.token_store import TokenStore
from src.calendar_watcher.classifier import to_meeting_event
from src.calendar_watcher.client import CalendarClient
from src.config import load_settings
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

    def _handle_api_post(self, parsed) -> None:
        suffix = parsed.path.removeprefix("/admin/api/")
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
        self._send_json({"error": "not found"}, status=404)

    def _is_authorized(self, parsed) -> bool:
        expected = load_settings().admin_token
        if not expected:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth.removeprefix("Bearer ").strip() == expected:
            return True
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        if query_token == expected:
            return True
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
        self.send_header("Content-Type", "audio/ogg")
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
            SELECT meet_code, event_id, scheduled_start_utc, title, status,
                   organizer, attendees,
                   transcript_path, summary_path, minutes_path, notes_path, audio_path,
                   attempts, last_error, delivered_at, created_at, updated_at
            FROM meetings
            ORDER BY scheduled_start_utc DESC, updated_at DESC
            LIMIT 200
            """
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def _meeting_detail(meet_code: str) -> dict:
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
    files["audio_segments"] = [_file_payload(path) for path in _audio_segment_paths(meet_code, settings.audio_dir)]
    meeting["files"] = files
    meeting["metadata"] = {
        "meet_code": meeting.get("meet_code"),
        "event_id": meeting.get("event_id"),
        "organizer": meeting.get("organizer"),
        "attendees": meeting.get("attendees"),
        "status": meeting.get("status"),
        "scheduled_start_utc": meeting.get("scheduled_start_utc"),
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
        if meeting["status"] in {"joining", "recording", "processing"}:
            return {"error": f"meeting already {meeting['status']}"}
        command_id = repo.request_rejoin(meet_code)
        return {"ok": True, "command_id": command_id, "meet_code": meet_code}
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
            stored = repo.get(meeting.meet_code) if meeting else None
            stored_status = stored["status"] if stored else None
            events.append(
                {
                    "event_id": raw.get("id"),
                    "title": raw.get("summary") or "Untitled meeting",
                    "start": raw.get("start"),
                    "end": raw.get("end"),
                    "meet_code": meeting.meet_code if meeting else None,
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
<main><section class="panel"><div class="panel-head"><h2>Upcoming</h2><div class="panel-actions"><button onclick="loadAll()">Refresh</button><button id="upcomingToggle" onclick="toggleUpcoming()">Show</button></div></div><div id="upcoming" class="collapsible collapsed"></div></section>
<section class="grid"><div class="panel"><h2>History</h2><div class="filters"><label class="sr-only" for="searchTitle">Search title</label><input id="searchTitle" name="searchTitle" placeholder="Search title…" autocomplete="off" oninput="renderMeetings(1)"><label class="sr-only" for="dateFrom">From date</label><input id="dateFrom" name="dateFrom" type="date" autocomplete="off" onchange="renderMeetings(1)"><label class="sr-only" for="dateTo">To date</label><input id="dateTo" name="dateTo" type="date" autocomplete="off" onchange="renderMeetings(1)"><button onclick="clearFilters()">Clear</button></div><div id="meetings"></div><div id="pagination" class="pagination"></div></div>
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
main{padding:18px;display:flex;flex-direction:column;gap:16px}.grid{display:grid;grid-template-columns:minmax(320px,430px) 1fr;gap:16px}
.panel{background:#0f172a;border:1px solid #263244;border-radius:8px;overflow:hidden;box-shadow:0 14px 40px rgba(0,0,0,.28)}.panel h2,.panel-head{padding:12px 14px;border-bottom:1px solid #263244}.panel-head{display:flex;align-items:center;justify-content:space-between}
button,input,.button-link{height:32px;border:1px solid #334155;background:#182235;color:#e5e7eb;border-radius:6px;padding:0 10px;touch-action:manipulation}button{cursor:pointer}button:hover,.button-link:hover{background:#22304a;border-color:#475569}button.danger{background:#451a1a;border-color:#7f1d1d;color:#fecaca}button.danger:hover{background:#5f1d1d;border-color:#991b1b}button:focus-visible,input:focus-visible,.button-link:focus-visible{outline:2px solid #38bdf8;outline-offset:2px}.button-link{display:inline-flex;align-items:center;text-decoration:none}input::placeholder{color:#64748b}.service-status{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:3px 9px;border:1px solid #334155;background:#111827;color:#e5e7eb;font-size:12px;line-height:1.3}.service-status:before{content:"";width:7px;height:7px;border-radius:999px;background:currentColor}.service-status.running{background:#102f20;border-color:#166534;color:#86efac}.service-status.degraded{background:#422006;border-color:#a16207;color:#fde68a}.service-status.failed{background:#451a1a;border-color:#991b1b;color:#fecaca}.service-status.starting{background:#172554;border-color:#1d4ed8;color:#93c5fd}.service-status.idle{background:#1f2937;border-color:#475569;color:#cbd5e1}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.settings-panel{max-width:760px}.settings-row{display:grid;grid-template-columns:180px 120px auto 1fr;gap:10px;align-items:center;padding:12px 14px}.filters{display:grid;grid-template-columns:minmax(0,1fr) minmax(112px,126px) minmax(112px,126px) auto;gap:8px;padding:12px 14px;border-bottom:1px solid #263244}.filters input{min-width:0}.filters input[type=date]{padding:0 6px;font-size:13px}.row{padding:10px 14px;border-bottom:1px solid #1f2937;cursor:pointer}.row:hover,.row.selected{background:#152033}.row.selected{box-shadow:inset 3px 0 0 #38bdf8}
.pagination{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 14px;border-top:1px solid #263244}.pagination .pager-actions{display:flex;gap:8px}.pagination button:disabled{opacity:.45;cursor:not-allowed}
.muted{color:#94a3b8}.status{display:inline-flex;align-items:center;gap:5px;border-radius:999px;padding:2px 8px;background:#1e293b;color:#c7d2fe;font-size:12px;line-height:1.35}.status:before{content:"";width:7px;height:7px;border-radius:999px;background:currentColor}.status.failed{background:#451a1a;color:#fecaca}.status.delivered{background:#102f20;color:#86efac}.status.no_one_joined{background:#1f2937;color:#cbd5e1}.status.recording,.status.processing{background:#422006;color:#fde68a}.status.scheduled{background:#172554;color:#93c5fd}.status.joining{background:#312e81;color:#c4b5fd}.status.upcoming{background:#0c2d48;color:#7dd3fc}.status.checking{background:#172554;color:#bfdbfe}.status.checking .dots span{animation:dotPulse 1.2s infinite;opacity:.25}.status.checking .dots span:nth-child(2){animation-delay:.2s}.status.checking .dots span:nth-child(3){animation-delay:.4s}@keyframes dotPulse{0%,80%,100%{opacity:.25}40%{opacity:1}}
.collapsible.collapsed{display:none}
.detail{min-height:520px}.empty-detail{padding:14px}.detail-body{padding:14px}.kv{display:grid;grid-template-columns:160px 1fr;gap:8px;padding:8px 0;border-bottom:1px solid #1f2937}.code-block{margin:12px 0 18px;border:1px solid #263244;border-radius:8px;overflow:hidden;background:#050914}.code-head{height:38px;display:flex;align-items:center;justify-content:space-between;padding:0 10px;background:#111827;border-bottom:1px solid #263244}.code-head h3{font-size:13px}.copy-btn{width:30px;height:30px;padding:0;display:inline-flex;align-items:center;justify-content:center}.copy-btn svg{width:15px;height:15px}.copied{background:#103224!important;border-color:#166534!important;color:#86efac!important}pre{white-space:pre-wrap;background:#050914;color:#e5e7eb;margin:0;padding:12px;max-height:360px;overflow:auto}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px 10px;border-bottom:1px solid #1f2937}.meet-mini{display:flex;align-items:center;gap:4px;margin-bottom:5px;color:#94a3b8;font-size:8.5px;line-height:1.2}.meet-mini-code{overflow-wrap:anywhere}.mini-icon{width:18px;height:18px;padding:0;display:inline-flex;align-items:center;justify-content:center;background:transparent;border:1px solid transparent;border-radius:5px;color:#94a3b8;text-decoration:none}.mini-icon:hover{background:#1e293b;border-color:#334155}.mini-icon svg{width:11px;height:11px}.login{min-height:100vh;display:grid;place-items:center;background:#070b12}.login-box{width:min(360px,calc(100vw - 32px));background:#0f172a;border:1px solid #263244;border-radius:8px;padding:20px;display:flex;flex-direction:column;gap:10px}.login-box input{height:36px;border:1px solid #334155;background:#070b12;color:#e5e7eb;border-radius:6px;padding:0 10px}.error{color:#fca5a5;margin:0}audio{width:min(560px,100%);height:34px;filter:invert(1) hue-rotate(180deg)}
@media(max-width:900px){.grid{grid-template-columns:1fr}.filters,.settings-row{grid-template-columns:1fr 1fr}.settings-row label{grid-column:1/-1}.upcoming-table th,.upcoming-table td{padding:8px 6px}.upcoming-table{table-layout:fixed}.upcoming-title{width:52%}.upcoming-time{width:24%}}
</style>"""


def _script(page: str = "dashboard") -> str:
    boot = "loadDashboard(); setInterval(loadStatus,15000);" if page == "dashboard" else "loadSettingsPage(); setInterval(loadStatus,15000);"
    return r"""
async function api(path, opts={}){const r=await fetch('/admin/api/'+path,{cache:'no-store',...opts}); if(!r.ok) throw new Error(await r.text()); return r.json();}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmt(v){if(!v)return ''; if(/^\d{4}-\d{2}-\d{2}$/.test(String(v)))return v; try{return new Date(v).toLocaleString();}catch{return v;}}
function badge(status){const labels={delivered:'Done',failed:'Fail',scheduled:'Sched',joining:'Join',recording:'Rec',processing:'Proc',no_one_joined:'Empty',cancelled:'Cancel',upcoming:'Upcoming'}; return `<span class="status ${esc(status)}">${esc(labels[status]||status)}</span>`}
function checkingBadge(){return `<span class="status checking">Checking<span class="dots"><span>.</span><span>.</span><span>.</span></span></span>`}
let allMeetings=[];
const urlState=new URLSearchParams(window.location.search);
let selectedMeeting=urlState.get('meeting')||'';
let currentPage=Number(urlState.get('page')||'1')||1;
let detailPollTimer=null;
let watchedMeeting='';
let pendingAction=null;
const pageSize=20;
async function loadAll(){await loadDashboard();}
async function loadDashboard(){await Promise.all([loadStatus(),loadUpcoming(),loadMeetings()]); if(selectedMeeting) await loadDetail(selectedMeeting,{push:false});}
async function loadSettingsPage(){await Promise.all([loadStatus(),loadSettings()]);}
async function loadStatus(){const d=await api('status'); const el=document.getElementById('status'); const state=String(d.state||'idle'); const labels={running:'Run',starting:'Boot',degraded:'Warn',failed:'Fail',idle:'Idle'}; el.className=`service-status ${esc(state)}`; el.title=[state,d.detail].filter(Boolean).join(': '); el.textContent=labels[state]||state.slice(0,4);}
async function loadSettings(){const d=await api('settings'); document.getElementById('audioRetentionDays').value=d.settings.audio_retention_days;}
async function saveRetention(){const days=Number(document.getElementById('audioRetentionDays').value); const msg=document.getElementById('settingsMsg'); const d=await api('settings/audio-retention',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({audio_retention_days:days})}); msg.textContent=`saved: ${d.settings.audio_retention_days} days`; setTimeout(()=>msg.textContent='',1600);}
async function loadUpcoming(){const d=await api('upcoming'); const tracked=d.events.filter(e=>e.qualifying); const rows=tracked.map(e=>`<tr><td class="upcoming-title">${meetMini(e.meet_code)}<strong>${esc(e.title)}</strong></td><td class="upcoming-time">${timeOnly(e.start)}</td><td class="upcoming-time">${timeOnly(e.end)}</td></tr>`).join(''); document.getElementById('upcoming').innerHTML=`<table class="upcoming-table"><thead><tr><th class="upcoming-title">Title</th><th class="upcoming-time">Start</th><th class="upcoming-time">End</th></tr></thead><tbody>${rows||'<tr><td colspan="3" class="muted">No tracked upcoming meetings.</td></tr>'}</tbody></table>`;}
function meetMini(code){if(!code)return ''; const href=`https://meet.google.com/${encodeURIComponent(code)}`; return `<div class="meet-mini"><span class="meet-mini-code">${esc(code)}</span><button class="mini-icon" onclick="copyText('${esc(code)}',this)" title="Copy meet ID" aria-label="Copy meet ID"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button><a class="mini-icon" href="${href}" target="_blank" rel="noopener noreferrer" title="Open Meet" aria-label="Open Meet"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.07 0l3.54-3.54a5 5 0 0 0-7.07-7.07L11.5 4.43"></path><path d="M14 11a5 5 0 0 0-7.07 0L3.39 14.54a5 5 0 0 0 7.07 7.07l2.04-2.04"></path></svg></a></div>`;}
function timeOnly(value){const raw=value?.dateTime||value?.date; if(!raw)return ''; if(/^\d{4}-\d{2}-\d{2}$/.test(String(raw)))return raw; try{return new Date(raw).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});}catch{return raw;}}
function toggleUpcoming(){const panel=document.getElementById('upcoming'); const btn=document.getElementById('upcomingToggle'); const collapsed=panel.classList.toggle('collapsed'); btn.textContent=collapsed?'Show':'Hide';}
async function loadMeetings(){const d=await api('meetings'); allMeetings=d.meetings; renderMeetings(currentPage,{push:false});}
function filteredMeetings(){const q=document.getElementById('searchTitle')?.value.trim().toLowerCase()||''; const from=document.getElementById('dateFrom')?.value||''; const to=document.getElementById('dateTo')?.value||''; return allMeetings.filter(m=>{const title=String(m.title||'').toLowerCase(); const day=localDateKey(m.scheduled_start_utc); return (!q||title.includes(q))&&(!from||day>=from)&&(!to||day<=to);});}
function updateUrl({code=selectedMeeting,page=currentPage,mode='push'}={}){const params=new URLSearchParams(window.location.search); if(code)params.set('meeting',code); else params.delete('meeting'); if(page&&page>1)params.set('page',String(page)); else params.delete('page'); const qs=params.toString(); const next=window.location.pathname+(qs?`?${qs}`:''); if(next!==window.location.pathname+window.location.search)history[mode==='replace'?'replaceState':'pushState']({},'',next);}
function renderMeetings(page=currentPage,{push=true}={}){const rows=filteredMeetings(); const totalPages=Math.max(1,Math.ceil(rows.length/pageSize)); currentPage=Math.min(Math.max(1,page),totalPages); const start=(currentPage-1)*pageSize; const pageRows=rows.slice(start,start+pageSize); document.getElementById('meetings').innerHTML=pageRows.map(m=>`<div class="row ${m.meet_code===selectedMeeting?'selected':''}" onclick="loadDetail('${esc(m.meet_code)}')"><strong>${esc(m.title)}</strong><div>${badge(m.status)} <span class="muted">${esc(m.meet_code)} · ${fmt(m.scheduled_start_utc)}</span></div></div>`).join('')||'<div class="row muted">No meetings.</div>'; renderPagination(rows.length,totalPages); if(push)updateUrl({page:currentPage,mode:'replace'});}
function renderPagination(total,totalPages){const el=document.getElementById('pagination'); if(!el)return; const start=total?((currentPage-1)*pageSize+1):0; const end=Math.min(currentPage*pageSize,total); el.innerHTML=`<span class="muted">${start}-${end} of ${total}</span><div class="pager-actions"><button onclick="renderMeetings(${currentPage-1})" ${currentPage<=1?'disabled':''}>Prev</button><button onclick="renderMeetings(${currentPage+1})" ${currentPage>=totalPages?'disabled':''}>Next</button></div>`;}
function clearFilters(){document.getElementById('searchTitle').value=''; document.getElementById('dateFrom').value=''; document.getElementById('dateTo').value=''; renderMeetings(1);}
function localDateKey(v){if(!v)return ''; const d=new Date(v); if(Number.isNaN(d.getTime()))return ''; const m=String(d.getMonth()+1).padStart(2,'0'); const day=String(d.getDate()).padStart(2,'0'); return `${d.getFullYear()}-${m}-${day}`;}
async function loadDetail(code,{push=true}={}){selectedMeeting=code; if(push)updateUrl({code,page:currentPage}); const d=await api('meetings/'+encodeURIComponent(code)); const m=d.meeting; const files=m.files||{}; if(pendingAction?.code===code&&m.status!==pendingAction.fromStatus)pendingAction=null; const statusHtml=pendingAction?.code===code?checkingBadge():badge(m.status); renderMeetings(currentPage,{push:false}); document.getElementById('detail').innerHTML=`<div class="detail-body"><h3>${esc(m.title)}</h3><p>${actionButtons(m)}</p>
${kv('Status',statusHtml)}${kv('Meet code',esc(m.meet_code))}${kv('Event ID',esc(m.event_id))}${kv('Host',esc(m.organizer||''))}${kv('Attendees',attendeeList(m.attendees))}${kv('Scheduled',fmt(m.scheduled_start_utc))}${kv('Delivered',fmt(m.delivered_at))}${kv('Audio',fileLine(files.audio))}${kv('Listen',audioPlayer(m))}${kv('Notes',fileLine(files.notes))}${kv('Minutes',fileLine(files.minutes))}${kv('Transcript',fileLine(files.transcript))}${m.last_error?kv('Error',esc(m.last_error)):''}
${codeBlock('Summary',files.summary?.content||'')}${codeBlock('Meeting Minutes',files.minutes?.content||'')}${codeBlock('Transcript',files.transcript?.content||'')}${codeBlock('Notes',files.notes?.content||'')}</div>`;}
function actionButtons(m){const rejoin=`<button onclick="rejoin('${esc(m.meet_code)}')">Rejoin</button>`; const out=m.status==='recording'?` <button class="danger" onclick="forceOut('${esc(m.meet_code)}')">Out</button>`:''; return rejoin+out;}
function swalOptions(extra){return {background:'#0f172a',color:'#e5e7eb',confirmButtonColor:'#2563eb',cancelButtonColor:'#475569',...extra};}
async function notify(icon,title,text=''){if(window.Swal){await Swal.fire(swalOptions({icon,title,text,toast:true,position:'top-end',timer:1800,showConfirmButton:false,timerProgressBar:true}));return;} console[icon==='error'?'error':'log']([title,text].filter(Boolean).join(' '));}
async function confirmDialog(title,text,confirmButtonText='Confirm'){if(window.Swal){const r=await Swal.fire(swalOptions({icon:'warning',title,text,showCancelButton:true,confirmButtonText,cancelButtonText:'Cancel',confirmButtonColor:'#dc2626'}));return r.isConfirmed;} console.warn([title,text].filter(Boolean).join(' ')); return false;}
function isActiveStatus(status){return ['scheduled','joining','recording','processing'].includes(String(status||''));}
function stopDetailPolling(){if(detailPollTimer){clearInterval(detailPollTimer); detailPollTimer=null;} watchedMeeting='';}
function startDetailPolling(code){watchedMeeting=code; if(detailPollTimer)clearInterval(detailPollTimer); detailPollTimer=setInterval(async()=>{if(!watchedMeeting)return; await loadMeetings(); const row=allMeetings.find(m=>m.meet_code===watchedMeeting); if(row&&pendingAction?.code===watchedMeeting&&row.status!==pendingAction.fromStatus)pendingAction=null; await loadDetail(watchedMeeting,{push:false}); if(row&&!isActiveStatus(row.status)&&!pendingAction)stopDetailPolling();},3000);}
async function queueAction(code,path,successText){const current=allMeetings.find(m=>m.meet_code===code); pendingAction={code,fromStatus:current?.status||''}; await loadDetail(code,{push:false}); startDetailPolling(code); try{const result=await api('meetings/'+encodeURIComponent(code)+'/'+path,{method:'POST'}); if(result.error){throw new Error(result.error);} await notify('success',successText);}catch(e){pendingAction=null; stopDetailPolling(); await loadDetail(code,{push:false}); await notify('error','Action failed',e.message||String(e));}}
async function rejoin(code){await queueAction(code,'rejoin','Rejoin queued');}
async function forceOut(code){const ok=await confirmDialog('Force bot out?', 'Bot will leave Meet and process transcript now.', 'Out'); if(!ok)return; await queueAction(code,'force-out','Out queued');}
window.addEventListener('popstate',async()=>{const params=new URLSearchParams(window.location.search); selectedMeeting=params.get('meeting')||''; currentPage=Number(params.get('page')||'1')||1; renderMeetings(currentPage,{push:false}); if(selectedMeeting)await loadDetail(selectedMeeting,{push:false}); else document.getElementById('detail').innerHTML='Select a meeting.';});
function kv(k,v){return `<div class="kv"><div class="muted">${k}</div><div>${v}</div></div>`}
function attendeeList(v){if(Array.isArray(v)&&v.length)return v.map(esc).join('<br>'); return 'missing';}
function fileLine(f){return f?.exists?`${esc(f.path)} <span class="muted">(${f.size} bytes)</span>`:'missing'}
function audioPlayer(m){const segments=m.files?.audio_segments||[]; if(!segments.length)return 'missing'; return segments.map((f,i)=>`<div><span class="muted">Segment ${i+1}</span><br><audio controls preload="none" src="/admin/api/meetings/${encodeURIComponent(m.meet_code)}/audio?index=${i}"></audio></div>`).join('');}
function codeBlock(title,content){const id='code_'+Math.random().toString(36).slice(2); return `<section class="code-block"><div class="code-head"><h3>${esc(title)}</h3><button class="copy-btn" onclick="copyCode('${id}',this)" title="Copy all" aria-label="Copy all"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button></div><pre id="${id}">${esc(content)}</pre></section>`}
async function flashCopied(button){button.classList.add('copied'); setTimeout(()=>button.classList.remove('copied'),900);}
async function copyCode(id,button){const text=document.getElementById(id)?.textContent||''; await navigator.clipboard.writeText(text); flashCopied(button);}
async function copyText(text,button){await navigator.clipboard.writeText(text); flashCopied(button);}
""" + boot + "\n"


def serve_forever() -> None:
    host = os.getenv("HEALTH_HOST", "0.0.0.0")
    port = int(os.getenv("HEALTH_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), AdminHandler)
    server.serve_forever()
