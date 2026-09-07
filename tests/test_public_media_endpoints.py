from datetime import UTC, datetime
from pathlib import Path

import pytest

from src import health_server
from src.auth.session_store import SessionStore
from src.auth.user_store import UserStore
from src.config import Settings
from src.models.meeting_event import MeetingEvent
from src.state.db import connect
from src.state.meetings_repo import MeetingsRepo

ADMIN_TOKEN = "test-admin-token"
AUDIO_BYTES = b"fake-opus-payload-0123456789"
PNG_BYTES = b"\x89PNG-fake"


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
    settings.audio_dir.mkdir(parents=True)
    (settings.audio_dir / "abc-defg-hij.opus").write_bytes(AUDIO_BYTES)
    shot_dir = settings.screenshot_dir / "abc-defg-hij"
    shot_dir.mkdir(parents=True)
    (shot_dir / "abc-defg-hij-20260907T000000Z.png").write_bytes(PNG_BYTES)
    conn = connect(settings.db_path)
    MeetingsRepo(conn).upsert(
        MeetingEvent(
            meet_code="abc-defg-hij",
            event_id="ev1",
            start_utc=datetime(2026, 9, 7, 9, 0, tzinfo=UTC),
            end_utc=None,
            title="Weekly Sync",
            organizer="owner@example.com",
            attendees=("a@example.com",),
        )
    )
    conn.close()
    from starlette.testclient import TestClient

    from src.web_app.app import create_app

    with TestClient(create_app()) as client:
        yield settings, client


def _get(client_and_path, headers: dict | None = None):
    client, path = client_and_path
    response = client.get(path, headers=headers or {})
    return response.status_code, response.headers, response.content


def test_audio_requires_auth(live_server) -> None:
    _, base = live_server
    status, _, _ = _get((base, "/api/meetings/abc-defg-hij/audio"))
    assert status == 401


def test_audio_full_and_range(live_server) -> None:
    _, base = live_server
    auth = {"X-API-Key": ADMIN_TOKEN}
    status, headers, body = _get((base, "/api/meetings/abc-defg-hij/audio"), auth)
    assert status == 200
    assert body == AUDIO_BYTES
    assert headers.get("Accept-Ranges") == "bytes"

    status, headers, body = _get((base, "/api/meetings/abc-defg-hij/audio"), {**auth, "Range": "bytes=0-3"})
    assert status == 206
    assert body == AUDIO_BYTES[:4]
    assert headers.get("Content-Range") == f"bytes 0-3/{len(AUDIO_BYTES)}"

    status, _, body = _get((base, "/api/meetings/abc-defg-hij/audio"), {**auth, "Range": "bytes=4-"})
    assert status == 206
    assert body == AUDIO_BYTES[4:]


def test_screenshot_serves_with_session_cookie(live_server) -> None:
    settings, base = live_server
    conn = connect(settings.db_path)
    try:
        user_id = UserStore(conn).create_user("viewer@example.com", password="secret-password-1")
        token = SessionStore(conn).create(user_id)
    finally:
        conn.close()
    status, _, body = _get((base, "/api/meetings/abc-defg-hij/screenshots?index=0"), {"Cookie": f"ma_session={token}"}
    )
    assert status == 200
    assert body == PNG_BYTES


def test_missing_media_is_404(live_server) -> None:
    _, base = live_server
    auth = {"X-API-Key": ADMIN_TOKEN}
    status, _, _ = _get((base, "/api/meetings/abc-defg-hij/screenshots?index=9"), auth)
    assert status == 404
