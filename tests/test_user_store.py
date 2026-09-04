import pytest

from src.auth.user_store import UserStore
from src.state.db import connect


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "test.db")
    yield UserStore(conn)
    conn.close()


def test_create_and_lookup_is_case_insensitive(store: UserStore) -> None:
    user_id = store.create_user("Alice@Example.COM", display_name="Alice")
    row = store.get_by_email("alice@example.com")
    assert row is not None
    assert row["id"] == user_id
    assert row["email"] == "alice@example.com"
    assert store.get_by_email("ALICE@EXAMPLE.COM")["id"] == user_id


def test_duplicate_email_raises(store: UserStore) -> None:
    store.create_user("dup@example.com")
    with pytest.raises(ValueError):
        store.create_user("DUP@example.com")


def test_verify_login_paths(store: UserStore) -> None:
    user_id = store.create_user("login@example.com", password="pw-1234")
    assert store.verify_login("login@example.com", "pw-1234")["id"] == user_id
    assert store.verify_login("login@example.com", "wrong") is None
    store.set_active(user_id, False)
    assert store.verify_login("login@example.com", "pw-1234") is None
    store.set_active(user_id, True)
    nopass_id = store.create_user("nopass@example.com")
    assert store.get_by_id(nopass_id)["password_hash"] is None
    assert store.verify_login("nopass@example.com", "") is None


def test_set_password_changes_login(store: UserStore) -> None:
    user_id = store.create_user("pw@example.com", password="old-pass")
    store.set_password(user_id, "new-pass")
    assert store.verify_login("pw@example.com", "old-pass") is None
    assert store.verify_login("pw@example.com", "new-pass")["id"] == user_id


def test_rotate_api_key_invalidates_old(store: UserStore) -> None:
    user_id = store.create_user("key@example.com")
    first = store.rotate_api_key(user_id)
    assert store.find_by_api_key(first)["id"] == user_id
    second = store.rotate_api_key(user_id)
    assert first != second
    assert store.find_by_api_key(first) is None
    assert store.find_by_api_key(second)["id"] == user_id


def test_revoke_api_key(store: UserStore) -> None:
    user_id = store.create_user("revoke@example.com")
    key = store.rotate_api_key(user_id)
    store.revoke_api_key(user_id)
    assert store.find_by_api_key(key) is None


def test_find_by_api_key_ignores_inactive_user(store: UserStore) -> None:
    user_id = store.create_user("gone@example.com")
    key = store.rotate_api_key(user_id)
    store.set_active(user_id, False)
    assert store.find_by_api_key(key) is None


def test_find_by_api_key_empty_input(store: UserStore) -> None:
    assert store.find_by_api_key("") is None


def test_seed_admin_only_on_empty_table(store: UserStore) -> None:
    row = store.seed_admin("Boss@Example.com")
    assert row is not None
    assert row["email"] == "boss@example.com"
    assert row["is_admin"] == 1
    assert row["password_hash"] is None and row["api_key_hash"] is None
    assert store.seed_admin("other@example.com") is None
    assert store.get_by_email("other@example.com") is None


def test_existing_db_gains_user_tables_without_touching_meetings(tmp_path) -> None:
    db_path = tmp_path / "existing.db"
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO meetings (meet_code, event_id, scheduled_start_utc, title, status)"
        " VALUES ('abc-defg-hij', 'ev1', '2026-09-01T00:00:00+00:00', 'Standup', 'delivered')"
    )
    conn.commit()
    conn.close()

    reopened = connect(db_path)
    tables = {row[0] for row in reopened.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "user_sessions"} <= tables
    row = reopened.execute("SELECT title, status FROM meetings WHERE meet_code='abc-defg-hij'").fetchone()
    assert (row["title"], row["status"]) == ("Standup", "delivered")
    UserStore(reopened).create_user("fresh@example.com")
    reopened.close()


def test_list_users_sorted_by_email(store: UserStore) -> None:
    store.create_user("b@example.com")
    store.create_user("a@example.com")
    emails = [row["email"] for row in store.list_users()]
    assert emails == ["a@example.com", "b@example.com"]
