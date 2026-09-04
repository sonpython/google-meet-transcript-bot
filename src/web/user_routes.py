"""Routes for the regular-user web surface: /login, /logout-user, /app,
/account/password.

handle() returns None for paths it does not own so the caller falls through
to its existing routing. Mutating routes require a live session context.
"""

from dataclasses import dataclass
from http import cookies as http_cookies
from pathlib import Path
from urllib.parse import parse_qs

from src.auth.request_auth import SESSION_COOKIE, AuthContext
from src.auth.session_store import SESSION_TTL_SECONDS, SessionStore
from src.auth.user_store import UserStore
from src.state.db import connect
from src.web.user_pages import app_html, login_html

ROUTES = {"/login", "/logout-user", "/app", "/account/password"}
MIN_PASSWORD_LENGTH = 10
LOGIN_ERROR = "Invalid email or password"


@dataclass(frozen=True)
class WebResponse:
    status: int
    content_type: str
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


def handle(
    method: str,
    path: str,
    headers,
    body: bytes,
    context: AuthContext | None,
    db_path: Path,
) -> WebResponse | None:
    if path not in ROUTES:
        return None
    route = (method, path)
    if route == ("GET", "/login"):
        if _session_context(context):
            return _redirect("/app")
        return _html(200, login_html())
    if route == ("POST", "/login"):
        return _post_login(body, db_path)
    if route == ("POST", "/logout-user"):
        return _post_logout(headers, db_path)
    if route == ("GET", "/app"):
        if not _session_context(context):
            return _redirect("/login")
        return _html(200, app_html(context.email or ""))
    if route == ("POST", "/account/password"):
        return _post_password(body, headers, context, db_path)
    return _html(405, "Method not allowed")


def _post_login(body: bytes, db_path: Path) -> WebResponse:
    form = parse_qs(body.decode("utf-8"))
    email = (form.get("email", [""])[0] or "").strip()
    password = form.get("password", [""])[0] or ""
    conn = connect(db_path)
    try:
        # Identical error for wrong password, unknown email, and inactive
        # account so the form does not leak which emails exist.
        row = UserStore(conn).verify_login(email, password) if email and password else None
        if row is None:
            return _html(401, login_html(LOGIN_ERROR))
        token = SessionStore(conn).create(int(row["id"]))
    finally:
        conn.close()
    return _redirect("/app", extra_headers=(_session_cookie(token),))


def _post_logout(headers, db_path: Path) -> WebResponse:
    token = _cookie_value(headers, SESSION_COOKIE)
    if token:
        conn = connect(db_path)
        try:
            SessionStore(conn).delete(token)
        finally:
            conn.close()
    return _redirect("/login", extra_headers=(_expired_session_cookie(),))


def _post_password(body: bytes, headers, context: AuthContext | None, db_path: Path) -> WebResponse:
    if not _session_context(context):
        return _redirect("/login")
    form = parse_qs(body.decode("utf-8"))
    current = form.get("current_password", [""])[0] or ""
    new = form.get("new_password", [""])[0] or ""
    if len(new) < MIN_PASSWORD_LENGTH:
        return _html(400, f"New password must be at least {MIN_PASSWORD_LENGTH} characters. Go back and retry.")
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        row = store.verify_login(context.email or "", current)
        if row is None:
            return _html(400, "Current password is incorrect. Go back and retry.")
        store.set_password(int(row["id"]), new)
        # Password change invalidates every session, then re-issues one for
        # this browser so the user is not logged out mid-flow.
        sessions = SessionStore(conn)
        sessions.delete_for_user(int(row["id"]))
        token = sessions.create(int(row["id"]))
    finally:
        conn.close()
    return _redirect("/app", extra_headers=(_session_cookie(token),))


def _session_context(context: AuthContext | None) -> bool:
    return context is not None and context.kind == "session"


def _session_cookie(token: str) -> tuple[str, str]:
    return (
        "Set-Cookie",
        f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}",
    )


def _expired_session_cookie() -> tuple[str, str]:
    return ("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")


def _cookie_value(headers, name: str) -> str:
    raw = headers.get("Cookie") or ""
    if not raw:
        return ""
    morsel = http_cookies.SimpleCookie(raw).get(name)
    return morsel.value if morsel else ""


def _html(status: int, content: str) -> WebResponse:
    return WebResponse(status, "text/html; charset=utf-8", content.encode("utf-8"))


def _redirect(location: str, extra_headers: tuple[tuple[str, str], ...] = ()) -> WebResponse:
    return WebResponse(303, "text/html; charset=utf-8", b"", (("Location", location), *extra_headers))
