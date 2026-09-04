"""Starts the MCP server as a supervised child of the main container process.

Mirrors the optional-subsystem convention of start_virtual_audio_if_enabled:
gated by MCP_ENABLED, safe to call twice, and a daemon thread respawns the
child after a short backoff so an MCP crash never takes the bot loop down.
"""

import os
import subprocess
import sys
import threading
import time

import structlog

RESTART_BACKOFF_SECONDS = 5
MCP_COMMAND = [sys.executable, "-m", "src.mcp_server"]

_started = threading.Lock()
_running = False
_stop_event = threading.Event()
_current_process: subprocess.Popen | None = None


def start_mcp_server_if_enabled() -> bool:
    global _running
    if os.getenv("MCP_ENABLED", "false").lower() != "true":
        return False
    with _started:
        if _running:
            return True
        _running = True
        _stop_event.clear()
    threading.Thread(target=_supervise, daemon=True, name="mcp-supervisor").start()
    return True


def _supervise() -> None:
    global _current_process
    log = structlog.get_logger(__name__)
    while not _stop_event.is_set():
        process = subprocess.Popen(MCP_COMMAND)
        _current_process = process
        log.info("mcp_server_started", pid=process.pid)
        code = process.wait()
        log.warning("mcp_server_exited", pid=process.pid, exit_code=code)
        _stop_event.wait(RESTART_BACKOFF_SECONDS)


def _stop_for_tests(timeout: float = 5.0) -> None:
    # Test-only teardown: production supervisors live for the container's life.
    global _running
    _stop_event.set()
    process = _current_process
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any(t.name == "mcp-supervisor" for t in threading.enumerate()):
            break
        time.sleep(0.05)
    with _started:
        _running = False
