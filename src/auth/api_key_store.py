"""Multiple named API keys per user, with optional expiry.

Only sha256 hashes are stored; the plaintext is returned once by create().
Expired rows are filtered on lookup and purged lazily when listing.
"""

from datetime import UTC, datetime, timedelta
from sqlite3 import Connection, Row

from src.auth.api_key import generate_api_key, hash_api_key

MAX_NAME_LENGTH = 60


class ApiKeyStore:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def create(self, user_id: int, name: str, expires_days: int | None = None) -> tuple[str, Row]:
        label = (name or "").strip()[:MAX_NAME_LENGTH] or "key"
        expires_at = None
        if expires_days is not None:
            days = int(expires_days)
            if days <= 0:
                raise ValueError("expires_days must be positive")
            expires_at = (datetime.now(UTC) + timedelta(days=days)).isoformat()
        plaintext = generate_api_key()
        cursor = self.conn.execute(
            "INSERT INTO api_keys (user_id, name, key_hash, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, label, hash_api_key(plaintext), expires_at),
        )
        self.conn.commit()
        return plaintext, self.get(int(cursor.lastrowid))

    def get(self, key_id: int) -> Row | None:
        return self.conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()

    def list_for_user(self, user_id: int) -> list[Row]:
        self.purge_expired()
        return list(
            self.conn.execute(
                "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                (user_id,),
            )
        )

    def delete(self, key_id: int, user_id: int) -> bool:
        # Owner-scoped: a user can only revoke their own keys.
        cursor = self.conn.execute(
            "DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_for_user(self, user_id: int) -> None:
        self.conn.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def find_user_by_key(self, plaintext: str) -> Row | None:
        if not plaintext:
            return None
        return self.conn.execute(
            """
            SELECT u.* FROM api_keys k
            JOIN users u ON u.id = k.user_id
            WHERE k.key_hash = ? AND u.is_active = 1
              AND (k.expires_at IS NULL OR k.expires_at > ?)
            """,
            (hash_api_key(plaintext), _now_iso()),
        ).fetchone()

    def purge_expired(self) -> None:
        self.conn.execute(
            "DELETE FROM api_keys WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (_now_iso(),),
        )
        self.conn.commit()

    def public_row(self, row: Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
        }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
