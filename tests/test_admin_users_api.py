import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from src import health_server
from src.auth.session_store import SessionStore
from src.auth.user_store import UserStore
from src.config import Settings
from src.state.db import connect
from src.web import admin_users

ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


def test_create_user_response_has_no_hash_fields(db_path: Path) -> None:
    result = admin_users.create_user(
        db_path, {"email": "New@Example.com", "display_name": "New", "password": "temp-password-1"}
    )
    assert result["ok"] is True
    user = result["user"]
    assert user["email"] == "new@example.com"
    assert user["has_password"] is True and user["has_api_key"] is False
    assert "password_hash" not in user and "api_key_hash" not in user
    assert "api_key" not in result


def test_create_user_validation_and_duplicates(db_path: Path) -> None:
    assert "error" in admin_users.create_user(db_path, {"email": "not-an-email"})
    admin_users.create_user(db_path, {"email": "dup@example.com"})
    assert "error" in admin_users.create_user(db_path, {"email": "dup@example.com"})


def test_rotate_key_shows_plaintext_once_and_invalidates_old(db_path: Path) -> None:
    user_id = admin_users.create_user(db_path, {"email": "key@example.com"})["user"]["id"]
    first = admin_users.rotate_key(db_path, user_id)
    assert first["api_key"].startswith("mak_")
    second = admin_users.rotate_key(db_path, user_id)
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        assert store.find_by_api_key(first["api_key"]) is None
        assert store.find_by_api_key(second["api_key"]) is not None
    finally:
        conn.close()


def test_revoke_key(db_path: Path) -> None:
    user_id = admin_users.create_user(db_path, {"email": "revoke@example.com"})["user"]["id"]
    key = admin_users.rotate_key(db_path, user_id)["api_key"]
    assert admin_users.revoke_key(db_path, user_id)["ok"] is True
    conn = connect(db_path)
    try:
        assert UserStore(conn).find_by_api_key(key) is None
    finally:
        conn.close()


def test_set_password_enforces_length_and_kills_sessions(db_path: Path) -> None:
    user_id = admin_users.create_user(db_path, {"email": "pw@example.com", "password": "first-password"})["user"]["id"]
    assert "error" in admin_users.set_password(db_path, user_id, {"password": "short"})
    conn = connect(db_path)
    try:
        token = SessionStore(conn).create(user_id)
    finally:
        conn.close()
    assert admin_users.set_password(db_path, user_id, {"password": "second-password"})["ok"] is True
    conn = connect(db_path)
    try:
        assert SessionStore(conn).get_user_id(token) is None
        assert UserStore(conn).verify_login("pw@example.com", "second-password") is not None
    finally:
        conn.close()


def test_deactivate_kills_sessions_and_api_key(db_path: Path) -> None:
    user_id = admin_users.create_user(db_path, {"email": "off@example.com"})["user"]["id"]
    key = admin_users.rotate_key(db_path, user_id)["api_key"]
    conn = connect(db_path)
    try:
        token = SessionStore(conn).create(user_id)
    finally:
        conn.close()
    assert admin_users.set_active(db_path, user_id, {"active": False})["ok"] is True
    conn = connect(db_path)
    try:
        assert SessionStore(conn).get_user_id(token) is None
        assert UserStore(conn).find_by_api_key(key) is None
    finally:
        conn.close()


def test_unknown_user_id_errors(db_path: Path) -> None:
    for result in (
        admin_users.set_password(db_path, 999, {"password": "long-enough-pw"}),
        admin_users.rotate_key(db_path, 999),
        admin_users.revoke_key(db_path, 999),
        admin_users.set_active(db_path, 999, {"active": False}),
    ):
        assert result == {"error": "user not found"}


def test_users_page_has_no_secret_material() -> None:
    page = admin_users.page_html()
    assert "password_hash" not in page and "api_key_hash" not in page
    assert "mak_" not in page


def test_users_page_offers_mcp_client_snippets() -> None:
    # After rotating a key the panel shows copy-ready client setups; the
    # snippets are built client-side from the one-time key, never server-side.
    page = admin_users.page_html()
    assert "claude mcp add --transport http meeting-assistant" in page
    assert "[mcp_servers.meeting-assistant]" in page
    assert "bearer_token" in page
    assert "showKeyPanel" in page


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
    server = health_server.AdminHTTPServer(("127.0.0.1", 0), health_server.AdminHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
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


def test_http_session_cookie_reads_public_api(live_server) -> None:
    settings, base = live_server
    conn = connect(settings.db_path)
    try:
        user_id = UserStore(conn).create_user("web@example.com", password="secret-password-1")
        token = SessionStore(conn).create(user_id)
    finally:
        conn.close()

    status, _ = _get(f"{base}/api/meetings", {"Cookie": f"ma_session={token}"})
    assert status == 200

    status, body = _get(f"{base}/admin/api/users", {"Cookie": f"ma_session={token}"})
    assert status == 403
    assert body == {"error": "forbidden"}


def test_http_admin_token_lists_users(live_server) -> None:
    settings, base = live_server
    admin_users.create_user(settings.db_path, {"email": "listed@example.com"})
    status, body = _get(f"{base}/admin/api/users", {"X-API-Key": ADMIN_TOKEN})
    assert status == 200
    assert body["users"][0]["email"] == "listed@example.com"
