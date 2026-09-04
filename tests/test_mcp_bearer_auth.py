import asyncio
from pathlib import Path

import pytest

from src.auth.user_store import UserStore
from src.mcp_server.bearer_auth import BearerAuthASGI, verify_key
from src.state.db import connect

ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "state.db"
    connect(path).close()
    return path


def _make_key(db_path: Path, email: str = "user@example.com") -> tuple[int, str]:
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        user_id = store.create_user(email)
        return user_id, store.rotate_api_key(user_id)
    finally:
        conn.close()


class _App:
    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        self.calls.append(scope["type"])
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


def _run(middleware, scope):
    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, None, send))
    return sent


def _http_scope(auth_header: str | None) -> dict:
    headers = [(b"authorization", auth_header.encode("latin-1"))] if auth_header is not None else []
    return {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}


def _status(sent) -> int:
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_no_header_and_wrong_scheme_are_401(db_path: Path) -> None:
    app = _App()
    middleware = BearerAuthASGI(app, db_path, ADMIN_TOKEN)
    assert _status(_run(middleware, _http_scope(None))) == 401
    assert _status(_run(middleware, _http_scope("Basic dXNlcjpwdw=="))) == 401
    assert _status(_run(middleware, _http_scope("Bearer unknown-token"))) == 401
    assert app.calls == []


def test_valid_user_key_passes(db_path: Path) -> None:
    _, key = _make_key(db_path)
    app = _App()
    middleware = BearerAuthASGI(app, db_path, ADMIN_TOKEN)
    sent = _run(middleware, _http_scope(f"Bearer {key}"))
    assert _status(sent) == 200
    assert app.calls == ["http"]


def test_deactivated_user_key_is_401(db_path: Path) -> None:
    user_id, key = _make_key(db_path)
    conn = connect(db_path)
    try:
        UserStore(conn).set_active(user_id, False)
    finally:
        conn.close()
    middleware = BearerAuthASGI(_App(), db_path, ADMIN_TOKEN)
    assert _status(_run(middleware, _http_scope(f"Bearer {key}"))) == 401


def test_admin_token_passes_and_unset_admin_rejects_empty(db_path: Path) -> None:
    middleware = BearerAuthASGI(_App(), db_path, ADMIN_TOKEN)
    assert _status(_run(middleware, _http_scope(f"Bearer {ADMIN_TOKEN}"))) == 200
    no_admin = BearerAuthASGI(_App(), db_path, "")
    assert _status(_run(no_admin, _http_scope("Bearer "))) == 401
    assert _status(_run(no_admin, _http_scope("Bearer " + ADMIN_TOKEN))) == 401


def test_lifespan_scope_passes_through(db_path: Path) -> None:
    app = _App()
    middleware = BearerAuthASGI(app, db_path, ADMIN_TOKEN)
    _run(middleware, {"type": "lifespan"})
    assert app.calls == ["lifespan"]


def test_verify_key_missing_db_file(tmp_path: Path) -> None:
    assert verify_key("mak_whatever", tmp_path / "missing.db", "") is False
