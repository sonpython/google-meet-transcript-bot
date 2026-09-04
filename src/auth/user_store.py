"""User account store backed by the shared SQLite database.

Plaintext API keys exist only in the return value of rotate_api_key; the
store persists sha256 hashes. Emails are casefolded so lookups are
case-insensitive.
"""

import sqlite3
from sqlite3 import Connection, Row

from src.auth.api_key import generate_api_key, hash_api_key
from src.auth.password_hash import hash_password, verify_password


class UserStore:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def create_user(
        self,
        email: str,
        display_name: str | None = None,
        password: str | None = None,
        is_admin: bool = False,
    ) -> int:
        normalized = _normalize_email(email)
        if not normalized:
            raise ValueError("email is required")
        password_hash = hash_password(password) if password else None
        try:
            cursor = self.conn.execute(
                """
                INSERT INTO users (email, display_name, password_hash, is_admin)
                VALUES (?, ?, ?, ?)
                """,
                (normalized, display_name, password_hash, 1 if is_admin else 0),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"user already exists: {normalized}") from exc
        self.conn.commit()
        return int(cursor.lastrowid)

    def get_by_email(self, email: str) -> Row | None:
        return self.conn.execute(
            "SELECT * FROM users WHERE email = ?", (_normalize_email(email),)
        ).fetchone()

    def get_by_id(self, user_id: int) -> Row | None:
        return self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def list_users(self) -> list[Row]:
        return list(self.conn.execute("SELECT * FROM users ORDER BY email"))

    def verify_login(self, email: str, password: str) -> Row | None:
        row = self.get_by_email(email)
        if row is None or not row["is_active"] or not row["password_hash"]:
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return row

    def set_password(self, user_id: int, password: str) -> None:
        self.conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (hash_password(password), user_id),
        )
        self.conn.commit()

    def rotate_api_key(self, user_id: int) -> str:
        plaintext = generate_api_key()
        self.conn.execute(
            "UPDATE users SET api_key_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (hash_api_key(plaintext), user_id),
        )
        self.conn.commit()
        return plaintext

    def revoke_api_key(self, user_id: int) -> None:
        self.conn.execute(
            "UPDATE users SET api_key_hash = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user_id,),
        )
        self.conn.commit()

    def set_active(self, user_id: int, active: bool) -> None:
        self.conn.execute(
            "UPDATE users SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (1 if active else 0, user_id),
        )
        self.conn.commit()

    def find_by_api_key(self, plaintext: str) -> Row | None:
        if not plaintext:
            return None
        return self.conn.execute(
            "SELECT * FROM users WHERE api_key_hash = ? AND is_active = 1",
            (hash_api_key(plaintext),),
        ).fetchone()

    def seed_admin(self, email: str) -> Row | None:
        # Bootstrap only: on a brand new users table, register USER_EMAIL as
        # the admin with no password/API key. ADMIN_TOKEN flows are untouched,
        # so the admin sets a password later through the admin UI.
        count = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count:
            return None
        user_id = self.create_user(email, is_admin=True)
        return self.get_by_id(user_id)


def _normalize_email(email: str) -> str:
    return email.strip().casefold()
