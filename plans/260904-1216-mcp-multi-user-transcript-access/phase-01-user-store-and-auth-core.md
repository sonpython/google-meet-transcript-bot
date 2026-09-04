# Phase 01 - User store and auth core

## Context Links

- Design: `plans/reports/brainstorm-260904-1216-mcp-multi-user-transcript-access.md` (Phase A, D4)
- Schema and migration pattern: `src/state/db.py:5` (SCHEMA), `src/state/db.py:60` (`connect`), `src/state/db.py:83` (`_ensure_column`)
- Repo style reference: `src/state/meetings_repo.py:11`
- Existing auth package: `src/auth/token_store.py`, `src/auth/oauth_user.py`

## Overview

- Priority: P1 (blocks 02, 03, 05)
- Status: done
- Effort: 3h
- Adds the `users` and `user_sessions` tables plus four small stdlib-only modules. No HTTP surface changes in this phase, so it ships safely on its own.

## Key Insights

- `connect()` runs `executescript(SCHEMA)` on every call (`src/state/db.py:66`), so `CREATE TABLE IF NOT EXISTS` is the migration mechanism for brand new tables. `_ensure_column` is only needed for new columns on existing tables, which this phase does not need.
- `connect()` is called per HTTP request in `src/health_server.py`, so seeding must not live in `connect()`. Seed once at process start.
- `hashlib.scrypt` with n=16384, r=8, p=1 needs about 16 MiB, under the 32 MiB OpenSSL default, so no `maxmem` tuning is needed. Larger n requires passing `maxmem` explicitly or it raises at runtime.
- Password login needs a server-side session, because the API key must never sit in a browser cookie (it is shown once and is a long-lived credential). A `user_sessions` table keeps sessions revocable on password change and deactivate.

## Requirements

Functional:
- Create a user with email, display name, optional password, admin flag.
- Verify a password and reject inactive users or users with no password set.
- Generate an API key once, return the plaintext once, store only sha256.
- Rotate and revoke an API key, look a user up by presented API key.
- Create, look up, and delete sessions with an expiry.
- Seed an admin row for `USER_EMAIL` when the users table is empty.

Non-functional:
- Standard library only: `hashlib`, `hmac`, `secrets`, `sqlite3`, `datetime`.
- Every module under 200 lines.
- Emails stored casefolded so lookups are case-insensitive.

## Architecture

Data flow:

```
plaintext password ─ hash_password ─> "scrypt$n$r$p$salt$hash" ─> users.password_hash
plaintext api key  ─ hash_api_key  ─> sha256 hex              ─> users.api_key_hash
session token      ─ sha256        ─> user_sessions.token_hash ─> users.id
```

Schema added to `SCHEMA` in `src/state/db.py`:

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    password_hash TEXT,
    api_key_hash TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS users_api_key_hash_idx
    ON users(api_key_hash) WHERE api_key_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS user_sessions_user_idx ON user_sessions(user_id);
```

`PRAGMA foreign_keys=ON` is already set at `src/state/db.py:65`, so the session cascade works.

## Related Code Files

Create:
- `src/auth/password_hash.py` - `hash_password(password) -> str`, `verify_password(password, stored) -> bool`. Format `scrypt$16384$8$1$<salt_b64>$<key_b64>`, 16-byte salt, dklen 32, `hmac.compare_digest` for the compare, returns `False` on any malformed stored value instead of raising.
- `src/auth/api_key.py` - `generate_api_key() -> str` returning `"mak_" + secrets.token_urlsafe(32)`, `hash_api_key(key) -> str` returning sha256 hex of the full string.
- `src/auth/user_store.py` - `UserStore(conn)` with `create_user`, `get_by_email`, `get_by_id`, `list_users`, `verify_login`, `set_password`, `rotate_api_key`, `revoke_api_key`, `set_active`, `find_by_api_key`, `seed_admin`.
- `src/auth/session_store.py` - `SessionStore(conn)` with `create(user_id) -> plaintext token`, `get_user_id(token) -> int | None`, `delete(token)`, `delete_for_user(user_id)`, `purge_expired()`. TTL constant `SESSION_TTL_SECONDS = 7 * 24 * 3600`.

Modify:
- `src/state/db.py` - append the two tables and two indexes to `SCHEMA`.

Create tests:
- `tests/test_password_hash.py`, `tests/test_api_key.py`, `tests/test_user_store.py`, `tests/test_session_store.py`

## Implementation Steps

1. Extend `SCHEMA` in `src/state/db.py` with `users`, `users_api_key_hash_idx`, `user_sessions`, `user_sessions_user_idx`. Do not touch `_ensure_column` calls.
2. Write `src/auth/password_hash.py`. Encode salt and key with `base64.urlsafe_b64encode`. `verify_password` splits on `$`, rejects any prefix other than `scrypt`, recomputes with the stored parameters, compares with `hmac.compare_digest`.
3. Write `src/auth/api_key.py`.
4. Write `src/auth/user_store.py`:
   - Every method casefolds and strips the email before use.
   - `create_user(email, display_name=None, password=None, is_admin=False)` raises `ValueError` on duplicate email (catch `sqlite3.IntegrityError`) and returns the new id.
   - `verify_login(email, password)` returns the row only when `is_active` is 1, `password_hash` is not null, and the hash verifies. Otherwise returns `None`.
   - `rotate_api_key(user_id)` generates a key, stores the hash, bumps `updated_at`, returns the plaintext. `revoke_api_key` sets the hash to NULL.
   - `find_by_api_key(plaintext)` hashes and selects `WHERE api_key_hash = ? AND is_active = 1`.
   - `set_password(user_id, password)` updates the hash and bumps `updated_at`.
   - `set_active(user_id, active)` updates the flag.
   - `seed_admin(email)` inserts `is_admin=1, is_active=1, password_hash=NULL, api_key_hash=NULL` only when `SELECT COUNT(*) FROM users` is 0, and returns the row or `None` when it did nothing. The seeded admin cannot log in with a password until an admin sets one, which is fine because the `ADMIN_TOKEN` path is untouched.
   - Every write commits explicitly, matching `src/state/meetings_repo.py`.
5. Write `src/auth/session_store.py`. Tokens are `secrets.token_urlsafe(32)`; only the sha256 hash is stored. `get_user_id` deletes and returns `None` when the row is expired. Expiry stored as ISO-8601 UTC to match the rest of the schema.
6. Write the four test modules.
7. Run `uv run pytest` and `uv run python -m compileall src tests`.

## Todo List

- [x] Extend `SCHEMA` in `src/state/db.py`
- [x] `src/auth/password_hash.py`
- [x] `src/auth/api_key.py`
- [x] `src/auth/user_store.py`
- [x] `src/auth/session_store.py`
- [x] `tests/test_password_hash.py`
- [x] `tests/test_api_key.py`
- [x] `tests/test_user_store.py`
- [x] `tests/test_session_store.py`
- [x] Full test suite green

## Test Matrix

| Level | Case | Expectation |
|-------|------|-------------|
| Unit | hash then verify | True |
| Unit | verify with wrong password | False |
| Unit | two hashes of the same password | different strings, both verify |
| Unit | verify against garbage, empty, or truncated stored value | False, no exception |
| Unit | `generate_api_key` twice | different, both start with `mak_` |
| Unit | `hash_api_key` | stable, 64 hex chars, differs from the plaintext |
| Unit | create then `get_by_email` with different case | same row |
| Unit | create duplicate email | `ValueError` |
| Unit | `verify_login` correct, wrong, inactive, no password | row, None, None, None |
| Unit | `rotate_api_key` twice | old key no longer resolves, new one does |
| Unit | `find_by_api_key` for a deactivated user | None |
| Unit | `seed_admin` on an empty DB then again | creates once, second call is a no-op |
| Unit | session create then `get_user_id` | user id |
| Unit | session expired (insert with a past `expires_at`) | None and row removed |
| Unit | `delete_for_user` | all sessions for that user gone |
| Integration | `connect()` on a pre-existing DB file that has meetings data | new tables created, meetings data intact |

## Success Criteria

- `uv run pytest` passes, including all existing tests.
- Opening a copy of a production-shaped DB with `connect()` adds the tables and leaves `meetings` rows untouched.
- No module in this phase exceeds 200 lines.
- No behavior change on any HTTP endpoint, confirmed by the untouched `tests/test_public_api.py`.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `executescript` on a live DB blocks writers | Low | Low | `CREATE TABLE IF NOT EXISTS` is a no-op after the first run; WAL is already enabled |
| scrypt cost too high for the container CPU | Low | Med | n=16384 needs about 100 ms and 16 MiB, well under defaults; measure in the test run |
| Seed writes a wrong admin email | Low | Low | Seed only when the table is empty and only from `USER_EMAIL`, admin can deactivate it |

## Security Considerations

- Passwords are never logged and never returned by any store method.
- The API key plaintext is returned exactly once by `rotate_api_key` and never persisted.
- Session tokens are stored hashed so a DB read cannot be replayed as a login.
- `find_by_api_key` and `verify_login` both filter on `is_active`, so deactivation is immediate for new requests, and phase 03 deletes sessions on deactivate.

## Rollback

Revert the commit. The two new tables can stay in place harmlessly; nothing reads them until phase 02.

## Next Steps

Phase 02 consumes `UserStore.find_by_api_key` and `SessionStore.get_user_id`.
