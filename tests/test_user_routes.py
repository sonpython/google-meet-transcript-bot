from pathlib import Path

import pytest

from src.auth.request_auth import AuthContext, authenticate
from src.auth.session_store import SessionStore
from src.auth.user_store import UserStore
from src.state.db import connect
from src.web.user_routes import handle

EMAIL = "user@example.com"
PASSWORD = "correct-horse-battery"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "state.db"
    conn = connect(path)
    try:
        UserStore(conn).create_user(EMAIL, password=PASSWORD)
    finally:
        conn.close()
    return path


def _session_ctx(db_path: Path, email: str = EMAIL) -> tuple[AuthContext, str]:
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        row = store.get_by_email(email)
        token = SessionStore(conn).create(int(row["id"]))
        return (
            AuthContext(kind="session", user_id=int(row["id"]), email=row["email"], is_admin=bool(row["is_admin"])),
            token,
        )
    finally:
        conn.close()


def _form(**fields) -> bytes:
    from urllib.parse import urlencode

    return urlencode(fields).encode("utf-8")


def _header_dict(response) -> dict:
    return dict(response.headers)


def test_login_success_sets_session_cookie(db_path: Path) -> None:
    response = handle("POST", "/login", {}, _form(email=EMAIL, password=PASSWORD), None, db_path)
    assert response.status == 303
    headers = _header_dict(response)
    assert headers["Location"] == "/app"
    cookie = headers["Set-Cookie"]
    assert cookie.startswith("ma_session=")
    assert "Path=/;" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    token = cookie.split(";")[0].removeprefix("ma_session=")
    conn = connect(db_path)
    try:
        assert SessionStore(conn).get_user_id(token) is not None
    finally:
        conn.close()


def test_login_failures_are_indistinguishable(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        inactive_id = store.create_user("inactive@example.com", password=PASSWORD)
        store.set_active(inactive_id, False)
    finally:
        conn.close()
    responses = [
        handle("POST", "/login", {}, _form(email=EMAIL, password="wrong-password"), None, db_path),
        handle("POST", "/login", {}, _form(email="ghost@example.com", password=PASSWORD), None, db_path),
        handle("POST", "/login", {}, _form(email="inactive@example.com", password=PASSWORD), None, db_path),
    ]
    bodies = {response.body for response in responses}
    assert all(response.status == 401 for response in responses)
    assert len(bodies) == 1


def test_app_requires_session(db_path: Path) -> None:
    response = handle("GET", "/app", {}, b"", None, db_path)
    assert response.status == 303
    assert _header_dict(response)["Location"] == "/login"
    api_key_ctx = AuthContext(kind="api_key", user_id=1, email=EMAIL)
    assert handle("GET", "/app", {}, b"", api_key_ctx, db_path).status == 303


def test_app_renders_read_only(db_path: Path) -> None:
    context, _ = _session_ctx(db_path)
    response = handle("GET", "/app", {}, b"", context, db_path)
    assert response.status == 200
    page = response.body.decode("utf-8")
    assert EMAIL in page
    # The shared stylesheet ships a .manual-join CSS rule; what must be absent
    # is any actual control or endpoint call, so check the JS symbols.
    for forbidden in ("Rejoin", "rejoin(", "deleteMeeting", "force-out", "forceOut", "regenerate", "manualJoin("):
        assert forbidden not in page


def test_login_page_redirects_when_already_signed_in(db_path: Path) -> None:
    context, _ = _session_ctx(db_path)
    response = handle("GET", "/login", {}, b"", context, db_path)
    assert response.status == 303
    assert _header_dict(response)["Location"] == "/app"


def test_logout_deletes_session_and_expires_cookie(db_path: Path) -> None:
    _, token = _session_ctx(db_path)
    response = handle("POST", "/logout-user", {"Cookie": f"ma_session={token}"}, b"", None, db_path)
    assert response.status == 303
    assert "Max-Age=0" in _header_dict(response)["Set-Cookie"]
    conn = connect(db_path)
    try:
        assert SessionStore(conn).get_user_id(token) is None
    finally:
        conn.close()


def test_password_change_wrong_current(db_path: Path) -> None:
    context, _ = _session_ctx(db_path)
    response = handle(
        "POST", "/account/password", {}, _form(current_password="nope", new_password="long-enough-pw"), context, db_path
    )
    assert response.status == 400
    conn = connect(db_path)
    try:
        assert UserStore(conn).verify_login(EMAIL, PASSWORD) is not None
    finally:
        conn.close()


def test_password_change_too_short(db_path: Path) -> None:
    context, _ = _session_ctx(db_path)
    response = handle(
        "POST", "/account/password", {}, _form(current_password=PASSWORD, new_password="short"), context, db_path
    )
    assert response.status == 400


def test_password_change_success_rotates_sessions(db_path: Path) -> None:
    context, old_token = _session_ctx(db_path)
    _, other_token = _session_ctx(db_path)
    response = handle(
        "POST",
        "/account/password",
        {},
        _form(current_password=PASSWORD, new_password="brand-new-password"),
        context,
        db_path,
    )
    assert response.status == 303
    new_cookie = _header_dict(response)["Set-Cookie"]
    new_token = new_cookie.split(";")[0].removeprefix("ma_session=")
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        assert store.verify_login(EMAIL, "brand-new-password") is not None
        assert store.verify_login(EMAIL, PASSWORD) is None
        sessions = SessionStore(conn)
        assert sessions.get_user_id(old_token) is None
        assert sessions.get_user_id(other_token) is None
        assert sessions.get_user_id(new_token) is not None
    finally:
        conn.close()


def test_session_cookie_authenticates_via_request_auth(db_path: Path) -> None:
    _, token = _session_ctx(db_path)
    context = authenticate(
        headers={"Cookie": f"ma_session={token}"}, query="", admin_token="admin-tok", db_path=db_path
    )
    assert context is not None and context.kind == "session" and context.email == EMAIL
