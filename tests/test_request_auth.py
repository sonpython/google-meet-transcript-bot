import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src import health_server
from src.auth.request_auth import authenticate
from src.auth.session_store import SessionStore
from src.auth.user_store import UserStore
from src.config import Settings
from src.models.meeting_event import MeetingEvent
from src.state.db import connect

ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


def _auth(db_path: Path, headers: dict, query: str = "", admin_token: str = ADMIN_TOKEN, allow_cookie: bool = True):
    return authenticate(
        headers=headers, query=query, admin_token=admin_token, db_path=db_path, allow_cookie=allow_cookie
    )


def _make_user(db_path: Path, email: str, is_admin: bool = False) -> tuple[int, str]:
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        user_id = store.create_user(email, is_admin=is_admin)
        return user_id, store.rotate_api_key(user_id)
    finally:
        conn.close()


def test_admin_token_via_all_channels(db_path: Path) -> None:
    assert _auth(db_path, {"Authorization": f"Bearer {ADMIN_TOKEN}"}).kind == "admin_token"
    assert _auth(db_path, {"X-API-Key": ADMIN_TOKEN}).is_admin
    assert _auth(db_path, {"X-Admin-Token": ADMIN_TOKEN}).is_admin
    assert _auth(db_path, {}, query=f"token={ADMIN_TOKEN}").is_admin


def test_admin_cookie_respects_allow_cookie(db_path: Path) -> None:
    headers = {"Cookie": f"admin_token={ADMIN_TOKEN}"}
    assert _auth(db_path, headers).kind == "admin_token"
    assert _auth(db_path, headers, allow_cookie=False) is None


def test_unset_admin_token_never_matches_empty_credentials(db_path: Path) -> None:
    assert _auth(db_path, {"Authorization": "Bearer "}, admin_token="") is None
    assert _auth(db_path, {"X-API-Key": ""}, admin_token="") is None
    assert _auth(db_path, {}, admin_token="") is None


def test_user_api_key_bearer_and_header(db_path: Path) -> None:
    user_id, key = _make_user(db_path, "user@example.com")
    for headers in ({"Authorization": f"Bearer {key}"}, {"X-API-Key": key}):
        context = _auth(db_path, headers)
        assert context.kind == "api_key"
        assert context.user_id == user_id
        assert context.email == "user@example.com"
        assert context.is_admin is False


def test_admin_flagged_user_key_is_admin(db_path: Path) -> None:
    _, key = _make_user(db_path, "boss@example.com", is_admin=True)
    assert _auth(db_path, {"X-API-Key": key}).is_admin is True


def test_deactivated_rotated_and_unknown_keys_fail(db_path: Path) -> None:
    user_id, key = _make_user(db_path, "gone@example.com")
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        store.set_active(user_id, False)
        assert _auth(db_path, {"X-API-Key": key}) is None
        store.set_active(user_id, True)
        new_key = store.rotate_api_key(user_id)
    finally:
        conn.close()
    assert _auth(db_path, {"X-API-Key": key}) is None
    assert _auth(db_path, {"X-API-Key": new_key}) is not None
    assert _auth(db_path, {"X-API-Key": "mak_totally-unknown"}) is None


def test_session_cookie_auth(db_path: Path) -> None:
    user_id, _ = _make_user(db_path, "web@example.com")
    conn = connect(db_path)
    try:
        token = SessionStore(conn).create(user_id)
    finally:
        conn.close()
    context = _auth(db_path, {"Cookie": f"ma_session={token}"})
    assert context.kind == "session"
    assert context.user_id == user_id
    assert _auth(db_path, {"Cookie": f"ma_session={token}"}, allow_cookie=False) is None


@pytest.fixture
def live_server(tmp_path: Path, monkeypatch):
    settings = Settings(
        db_path=tmp_path / "state.db",
        audio_dir=tmp_path / "audio",
        output_dir=tmp_path / "output",
        debug_dir=tmp_path / "debug",
        screenshot_dir=tmp_path / "screenshots",
        user_email="owner@example.com",
        admin_token=ADMIN_TOKEN,
    )
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)
    conn = connect(settings.db_path)
    try:
        from src.state.meetings_repo import MeetingsRepo

        MeetingsRepo(conn).upsert(
            MeetingEvent(
                meet_code="abc-defg-hij",
                event_id="ev1",
                start_utc=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
                end_utc=None,
                title="Weekly Sync",
                organizer="owner@example.com",
                attendees=("a@example.com",),
            )
        )
    finally:
        conn.close()
    server = health_server.AdminHTTPServer(("127.0.0.1", 0), health_server.AdminHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield settings, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _get(url: str, headers: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def test_http_user_key_reads_api_but_not_admin(live_server) -> None:
    settings, base = live_server
    _, key = _make_user(settings.db_path, "user@example.com")

    status, body = _get(f"{base}/api/meetings", {"Authorization": f"Bearer {key}"})
    assert status == 200
    assert body["pagination"]["total"] == 1

    status, body = _get(f"{base}/admin/api/meetings", {"Authorization": f"Bearer {key}"})
    assert status == 403
    assert body == {"error": "forbidden"}


def test_http_admin_token_still_works_everywhere(live_server) -> None:
    _, base = live_server
    for path in ("/api/meetings", "/admin/api/meetings"):
        status, _ = _get(f"{base}{path}", {"X-API-Key": ADMIN_TOKEN})
        assert status == 200


def test_http_no_credentials_is_401(live_server) -> None:
    _, base = live_server
    status, body = _get(f"{base}/api/meetings")
    assert status == 401
    assert body == {"error": "unauthorized"}
