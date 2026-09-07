from pathlib import Path

import pytest

from src import health_server
from src.config import Settings
from src.state.db import connect

ADMIN_TOKEN = "test-admin-token"

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
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
    connect(settings.db_path).close()
    from starlette.testclient import TestClient

    from src.web_app.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def test_mcp_mounted_requires_bearer(client) -> None:
    response = client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    assert response.status_code == 401


def test_mcp_mounted_initializes_with_admin_token(client) -> None:
    response = client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": f"Bearer {ADMIN_TOKEN}"}
    )
    assert response.status_code == 200
    assert "meeting-assistant" in response.text


def test_healthz_still_serves(client) -> None:
    assert client.get("/healthz").status_code == 200
