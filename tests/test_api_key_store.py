from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.auth.api_key_store import ApiKeyStore
from src.auth.user_store import UserStore
from src.state.db import connect


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "state.db")
    yield connection
    connection.close()


@pytest.fixture
def user_id(conn):
    return UserStore(conn).create_user("keys@example.com")


def test_create_multiple_named_keys(conn, user_id) -> None:
    store = ApiKeyStore(conn)
    key1, row1 = store.create(user_id, "laptop")
    key2, row2 = store.create(user_id, "codex", expires_days=30)
    assert key1 != key2
    assert row1["expires_at"] is None
    assert row2["expires_at"] is not None
    rows = store.list_for_user(user_id)
    assert {row["name"] for row in rows} == {"laptop", "codex"}
    assert store.find_user_by_key(key1)["id"] == user_id
    assert store.find_user_by_key(key2)["id"] == user_id


def test_expired_key_rejected_and_purged(conn, user_id) -> None:
    store = ApiKeyStore(conn)
    key, row = store.create(user_id, "short", expires_days=1)
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    conn.execute("UPDATE api_keys SET expires_at = ? WHERE id = ?", (past, row["id"]))
    conn.commit()
    assert store.find_user_by_key(key) is None
    assert store.list_for_user(user_id) == []


def test_revoke_is_owner_scoped(conn, user_id) -> None:
    store = ApiKeyStore(conn)
    other_id = UserStore(conn).create_user("other@example.com")
    key, row = store.create(user_id, "mine")
    assert store.delete(row["id"], other_id) is False
    assert store.find_user_by_key(key) is not None
    assert store.delete(row["id"], user_id) is True
    assert store.find_user_by_key(key) is None


def test_invalid_expiry_rejected(conn, user_id) -> None:
    with pytest.raises(ValueError):
        ApiKeyStore(conn).create(user_id, "bad", expires_days=0)


def test_legacy_column_migrates_once_and_revoke_sticks(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    conn = connect(db_path)
    user_id = UserStore(conn).create_user("legacy@example.com")
    # simulate a pre-migration database: key hash lives in the users column
    from src.auth.api_key import generate_api_key, hash_api_key

    legacy_key = generate_api_key()
    conn.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE users SET api_key_hash = ? WHERE id = ?", (hash_api_key(legacy_key), user_id))
    conn.commit()
    conn.close()

    # reconnect runs the migration: legacy key works through the new table
    conn = connect(db_path)
    store = ApiKeyStore(conn)
    assert store.find_user_by_key(legacy_key)["id"] == user_id
    assert conn.execute("SELECT api_key_hash FROM users WHERE id = ?", (user_id,)).fetchone()[0] is None
    # revoke, then reconnect again: the key must NOT be resurrected
    row = store.list_for_user(user_id)[0]
    store.delete(row["id"], user_id)
    conn.close()
    conn = connect(db_path)
    assert ApiKeyStore(conn).find_user_by_key(legacy_key) is None
    conn.close()


def test_admin_rotate_resets_all_keys(conn, user_id) -> None:
    users = UserStore(conn)
    store = ApiKeyStore(conn)
    personal, _ = store.create(user_id, "personal")
    fresh = users.rotate_api_key(user_id)
    assert store.find_user_by_key(personal) is None
    assert store.find_user_by_key(fresh)["id"] == user_id
    assert [row["name"] for row in store.list_for_user(user_id)] == ["admin-issued"]
