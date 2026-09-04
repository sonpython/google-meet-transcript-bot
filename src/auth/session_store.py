"""Server-side web sessions for password logins.

The browser cookie carries a random token; only its sha256 hash is stored,
so a database read cannot be replayed as a login. Sessions are revocable
per user (password change, deactivation).
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection

SESSION_TTL_SECONDS = 7 * 24 * 3600


class SessionStore:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def create(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(seconds=SESSION_TTL_SECONDS)
        self.conn.execute(
            "INSERT INTO user_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (_hash_token(token), user_id, expires_at.isoformat()),
        )
        self.conn.commit()
        return token

    def get_user_id(self, token: str) -> int | None:
        if not token:
            return None
        token_hash = _hash_token(token)
        row = self.conn.execute(
            "SELECT user_id, expires_at FROM user_sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        if _is_expired(row["expires_at"]):
            self.conn.execute("DELETE FROM user_sessions WHERE token_hash = ?", (token_hash,))
            self.conn.commit()
            return None
        return int(row["user_id"])

    def delete(self, token: str) -> None:
        self.conn.execute("DELETE FROM user_sessions WHERE token_hash = ?", (_hash_token(token),))
        self.conn.commit()

    def delete_for_user(self, user_id: int) -> None:
        self.conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def purge_expired(self) -> None:
        self.conn.execute(
            "DELETE FROM user_sessions WHERE expires_at < ?",
            (datetime.now(UTC).isoformat(),),
        )
        self.conn.commit()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_expired(expires_at: str) -> bool:
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry < datetime.now(UTC)
