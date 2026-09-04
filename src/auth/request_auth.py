"""Request authentication shared by the admin HTTP server and the MCP server.

Order of precedence: ADMIN_TOKEN (legacy, full admin), then a personal API
key, then the web session cookie. The database is only opened after the
admin-token branch misses, so admin traffic never pays for a DB lookup.
"""

import hmac
from dataclasses import dataclass
from http import cookies as http_cookies
from pathlib import Path
from urllib.parse import parse_qs

from src.auth.session_store import SessionStore
from src.auth.user_store import UserStore
from src.state.db import connect

SESSION_COOKIE = "ma_session"


@dataclass(frozen=True)
class AuthContext:
    kind: str  # admin_token | api_key | session
    user_id: int | None = None
    email: str | None = None
    is_admin: bool = False


def authenticate(
    headers,
    query: str,
    admin_token: str,
    db_path: Path,
    allow_cookie: bool = True,
) -> AuthContext | None:
    auth_header = (headers.get("Authorization") or "").strip()
    bearer = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
    x_api_key = (headers.get("X-API-Key") or "").strip()
    x_admin_token = (headers.get("X-Admin-Token") or "").strip()
    query_token = parse_qs(query).get("token", [""])[0]

    if admin_token:
        for candidate in (bearer, x_api_key, x_admin_token, query_token):
            if candidate and _equal(candidate, admin_token):
                return AuthContext(kind="admin_token", is_admin=True)
        if allow_cookie:
            cookie_token = _cookie_value(headers, "admin_token")
            if cookie_token and _equal(cookie_token, admin_token):
                return AuthContext(kind="admin_token", is_admin=True)

    # Personal API keys arrive only via Bearer or X-API-Key; X-Admin-Token and
    # ?token= stay reserved for the legacy admin token.
    for candidate in (bearer, x_api_key):
        if candidate:
            context = _authenticate_api_key(candidate, db_path)
            if context is not None:
                return context

    if allow_cookie:
        session_token = _cookie_value(headers, SESSION_COOKIE)
        if session_token:
            return _authenticate_session(session_token, db_path)
    return None


def _authenticate_api_key(candidate: str, db_path: Path) -> AuthContext | None:
    conn = connect(db_path)
    try:
        row = UserStore(conn).find_by_api_key(candidate)
    finally:
        conn.close()
    if row is None:
        return None
    return AuthContext(
        kind="api_key", user_id=int(row["id"]), email=row["email"], is_admin=bool(row["is_admin"])
    )


def _authenticate_session(token: str, db_path: Path) -> AuthContext | None:
    conn = connect(db_path)
    try:
        user_id = SessionStore(conn).get_user_id(token)
        if user_id is None:
            return None
        row = UserStore(conn).get_by_id(user_id)
    finally:
        conn.close()
    if row is None or not row["is_active"]:
        return None
    return AuthContext(
        kind="session", user_id=int(row["id"]), email=row["email"], is_admin=bool(row["is_admin"])
    )


def _cookie_value(headers, name: str) -> str:
    raw = headers.get("Cookie") or ""
    if not raw:
        return ""
    morsel = http_cookies.SimpleCookie(raw).get(name)
    return morsel.value if morsel else ""


def _equal(candidate: str, expected: str) -> bool:
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
