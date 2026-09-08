from pathlib import Path

import pytest

from src import health_server
from src.auth.session_store import SessionStore
from src.auth.user_store import UserStore
from src.config import Settings
from src.state.db import connect

ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def client_env(tmp_path: Path, monkeypatch):
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
        user_id = UserStore(conn).create_user("keys@example.com", password="secret-password-1")
        token = SessionStore(conn).create(user_id)
    finally:
        conn.close()
    from starlette.testclient import TestClient

    from src.web_app.app import create_app

    with TestClient(create_app()) as client:
        yield client, {"Cookie": f"ma_session={token}"}, settings


def test_session_creates_lists_uses_and_revokes_key(client_env) -> None:
    client, session, _ = client_env
    created = client.post("/api/keys", json={"name": "laptop", "expires_days": 30}, headers=session).json()
    assert created["ok"] is True
    assert created["api_key"].startswith("mak_")
    assert created["key"]["name"] == "laptop"
    assert created["key"]["expires_at"] is not None

    keys = client.get("/api/keys", headers=session).json()["keys"]
    assert len(keys) == 1 and "key_hash" not in keys[0]

    # the fresh key authenticates on the API
    assert client.get("/api/meetings", headers={"Authorization": f"Bearer {created['api_key']}"}).status_code == 200

    revoke = client.post(f"/api/keys/{keys[0]['id']}/revoke", headers=session)
    assert revoke.status_code == 200
    assert client.get("/api/meetings", headers={"Authorization": f"Bearer {created['api_key']}"}).status_code == 401
    assert client.get("/api/keys", headers=session).json()["keys"] == []


def test_key_management_rejects_non_session_auth(client_env) -> None:
    client, session, _ = client_env
    key = client.post("/api/keys", json={"name": "k"}, headers=session).json()["api_key"]
    bearer = {"Authorization": f"Bearer {key}"}
    assert client.get("/api/keys", headers=bearer).status_code == 403
    assert client.post("/api/keys", json={"name": "evil"}, headers=bearer).status_code == 403
    admin = {"X-API-Key": ADMIN_TOKEN}
    assert client.get("/api/keys", headers=admin).status_code == 403
    assert client.get("/api/keys").status_code == 401


def test_manual_join_open_to_users_but_not_anonymous(client_env) -> None:
    client, session, _ = client_env
    # invalid code exercises the endpoint without needing a live scheduler
    response = client.post("/api/manual-join", json={"meet_code": "not a code"}, headers=session)
    assert response.status_code == 200
    assert response.json() == {"error": "invalid Meet code"}
    assert client.post("/api/manual-join", json={"meet_code": "abc-defg-hij"}).status_code == 401


def test_revoking_someone_elses_key_is_404(client_env) -> None:
    client, session, settings = client_env
    conn = connect(settings.db_path)
    try:
        other_id = UserStore(conn).create_user("other@example.com", password="secret-password-2")
        other_token = SessionStore(conn).create(other_id)
    finally:
        conn.close()
    key_id = client.post("/api/keys", json={"name": "mine"}, headers=session).json()["key"]["id"]
    response = client.post(f"/api/keys/{key_id}/revoke", headers={"Cookie": f"ma_session={other_token}"})
    assert response.status_code == 404
    assert client.get("/api/keys", headers=session).json()["keys"] != []
