from datetime import UTC, datetime, timedelta

import pytest

from src.auth.session_store import SessionStore, _hash_token
from src.auth.user_store import UserStore
from src.state.db import connect


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def sessions(conn):
    return SessionStore(conn)


@pytest.fixture
def user_id(conn):
    return UserStore(conn).create_user("session@example.com")


def test_create_then_resolve(sessions: SessionStore, user_id: int) -> None:
    token = sessions.create(user_id)
    assert sessions.get_user_id(token) == user_id


def test_unknown_or_empty_token(sessions: SessionStore) -> None:
    assert sessions.get_user_id("does-not-exist") is None
    assert sessions.get_user_id("") is None


def test_expired_session_removed(sessions: SessionStore, conn, user_id: int) -> None:
    token = sessions.create(user_id)
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    conn.execute(
        "UPDATE user_sessions SET expires_at = ? WHERE token_hash = ?",
        (past, _hash_token(token)),
    )
    conn.commit()
    assert sessions.get_user_id(token) is None
    remaining = conn.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0]
    assert remaining == 0


def test_delete_single_session(sessions: SessionStore, user_id: int) -> None:
    token = sessions.create(user_id)
    sessions.delete(token)
    assert sessions.get_user_id(token) is None


def test_delete_for_user_removes_all(sessions: SessionStore, user_id: int) -> None:
    first = sessions.create(user_id)
    second = sessions.create(user_id)
    sessions.delete_for_user(user_id)
    assert sessions.get_user_id(first) is None
    assert sessions.get_user_id(second) is None


def test_purge_expired_keeps_live_sessions(sessions: SessionStore, conn, user_id: int) -> None:
    live = sessions.create(user_id)
    stale = sessions.create(user_id)
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    conn.execute(
        "UPDATE user_sessions SET expires_at = ? WHERE token_hash = ?",
        (past, _hash_token(stale)),
    )
    conn.commit()
    sessions.purge_expired()
    assert sessions.get_user_id(live) == user_id
    assert sessions.get_user_id(stale) is None


def test_only_hashes_stored(sessions: SessionStore, conn, user_id: int) -> None:
    token = sessions.create(user_id)
    stored = [row["token_hash"] for row in conn.execute("SELECT token_hash FROM user_sessions")]
    assert token not in stored
    assert _hash_token(token) in stored
