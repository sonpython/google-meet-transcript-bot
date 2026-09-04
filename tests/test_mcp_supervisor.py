import sys
import threading
import time

import pytest

from src.mcp_server import supervisor


@pytest.fixture(autouse=True)
def clean_supervisor(monkeypatch):
    monkeypatch.setattr(supervisor, "RESTART_BACKOFF_SECONDS", 0.05)
    yield
    supervisor._stop_for_tests()


def test_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MCP_ENABLED", raising=False)
    assert supervisor.start_mcp_server_if_enabled() is False
    monkeypatch.setenv("MCP_ENABLED", "false")
    assert supervisor.start_mcp_server_if_enabled() is False
    assert not any(t.name == "mcp-supervisor" for t in threading.enumerate())


def test_enabled_spawns_and_respawns_real_child(monkeypatch, tmp_path) -> None:
    marker = tmp_path / "spawns.log"
    code = f"open({str(marker)!r}, 'a').write('x')"
    monkeypatch.setattr(supervisor, "MCP_COMMAND", [sys.executable, "-c", code])
    monkeypatch.setenv("MCP_ENABLED", "true")
    assert supervisor.start_mcp_server_if_enabled() is True
    deadline = time.time() + 5
    while time.time() < deadline:
        if marker.exists() and len(marker.read_text()) >= 2:
            break
        time.sleep(0.05)
    # The short-lived child exited and was respawned at least once.
    assert len(marker.read_text()) >= 2


def test_second_call_is_noop(monkeypatch) -> None:
    monkeypatch.setattr(supervisor, "MCP_COMMAND", [sys.executable, "-c", "import time; time.sleep(30)"])
    monkeypatch.setenv("MCP_ENABLED", "true")
    assert supervisor.start_mcp_server_if_enabled() is True
    assert supervisor.start_mcp_server_if_enabled() is True
    names = [t.name for t in threading.enumerate() if t.name == "mcp-supervisor"]
    assert len(names) == 1
