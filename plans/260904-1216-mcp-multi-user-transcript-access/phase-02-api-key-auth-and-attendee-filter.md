# Phase 02 - API key auth and attendee filter

## Context Links

- Design: brainstorm Phase A bullets 3 and 5 (`/api/*` accepts per-user API key, new `attendee` filter)
- Current auth gate: `src/health_server.py:180` (`_is_authorized`), called at `:35`, `:41`, `:47`, `:53`, `:69`
- Current filter builder: `src/health_server.py:344` (`_meeting_filter_sql`), used at `:314` and `:336`
- Filter echo: `src/health_server.py:426`
- Existing API tests: `tests/test_public_api.py`

## Overview

- Priority: P1 (blocks 03 and 05)
- Status: done
- Effort: 2h
- Server-side only. Adds per-user API key auth to `/api/*`, an explicit admin gate on `/admin/*`, and the `attendee` filter. Extracts the reusable query helpers that phase 05 needs.

## Key Insights

- Today one flat token authorizes both `/api/*` and `/admin/*` (`src/health_server.py:180-202`). The moment a user API key passes `_is_authorized`, a regular user would also reach `/admin/api/meetings/{code}/delete`. The admin gate is not optional, it is the core correctness item of this phase.
- `_is_authorized` currently returns `False` whenever `admin_token` is unset (`src/health_server.py:181-183`). Keep that short circuit for the token branch so an empty env var never matches an empty header.
- `tests/test_public_api.py:38` monkeypatches `health_server.load_settings`. Any helper moved out of `health_server` must therefore take `db_path` as an argument instead of calling `load_settings()` itself, otherwise existing tests silently read the wrong DB.
- `meetings.attendees` is a JSON array of emails written at `src/health_server.py:547` and decoded at `src/health_server.py:981`. A `LIKE` match over `attendees` plus `organizer` is enough, because D2 makes this a convenience filter, not an access boundary.

## Requirements

Functional:
- `/api/*` accepts, in order: `ADMIN_TOKEN` exactly as today, then an active user's API key via `Authorization: Bearer` or `X-API-Key`.
- `/admin/*` accepts `ADMIN_TOKEN` as today, and an authenticated user only when that user is an admin.
- `attendee=<email>` filters `/api/meetings` and `/api/transcripts`, and appears in the echoed filters.
- Unauthenticated stays 401. Authenticated but not admin on `/admin/*` is 403 with a JSON body.

Non-functional:
- Zero behavior change for `ADMIN_TOKEN` callers, including `?token=`, `X-Admin-Token`, and the `/admin` cookie.
- The DB is only touched when the admin token check fails, so admin traffic keeps its current latency.

## Architecture

```
HTTP request
  ├─ headers + query + cookie ─> request_auth.authenticate(...)
  │     1. ADMIN_TOKEN match  -> AuthContext(kind="admin_token", is_admin=True)
  │     2. user API key       -> UserStore.find_by_api_key -> AuthContext(kind="api_key", user_id, email, is_admin)
  │     3. session cookie     -> SessionStore.get_user_id  -> AuthContext(kind="session", ...)   [phase 03 uses this]
  │     4. no match           -> None
  └─ route guard: /admin/* requires ctx.is_admin, /api/* requires ctx
```

`AuthContext` is a frozen dataclass: `kind`, `user_id`, `email`, `is_admin`.

## Related Code Files

Create:
- `src/auth/request_auth.py` - `AuthContext` and `authenticate(headers, query, cookie_header, db_path, admin_token, allow_cookie)`. Pure inputs, so it is unit testable without an HTTP server. Under 120 lines.
- `src/state/meeting_queries.py` - helpers moved verbatim out of `health_server` plus the new attendee clause: `first_param`, `bounded_int`, `truthy`, `range_boundary`, `normalize_meet_code`, `decode_attendees`, `meeting_filter_sql`, `resolve_meeting_paths`, `path_or_none`.

Modify:
- `src/health_server.py`
  - Replace the moved function bodies with aliased imports so every existing call site keeps its current name:
    `from src.state.meeting_queries import bounded_int as _bounded_int, first_param as _first_param, ...`
  - `_is_authorized` becomes a thin wrapper that builds the inputs, calls `authenticate`, stores the result on `self.auth_context`, and returns a bool.
  - Add `_require_admin(parsed)` used by the `/admin` and `/admin/api/` branches at `:34`, `:40`, `:46`, `:68`.
  - `/api/*` branch at `:52` keeps `allow_cookie=False` in this phase. Phase 03 flips it to allow the session cookie.
  - `_api_filter_echo` at `:426`: add `"attendee"` to the key tuple.

Tests:
- Create `tests/test_request_auth.py`
- Extend `tests/test_public_api.py` with attendee filter cases

## Implementation Steps

1. Create `src/state/meeting_queries.py`. Move the bodies of `_first_param` (`:431`), `_bounded_int` (`:436`), `_truthy` (`:446`), `_range_boundary` (`:450`), `_normalize_meet_code` (`:684`), `_decode_attendees` (`:981`), `_meeting_paths` (`:775`), `_path_or_none` (`:995`), `_meeting_filter_sql` (`:344`) unchanged except for dropping the leading underscore. None of them call `load_settings`, so the move is behavior neutral.
2. In `meeting_filter_sql`, add the attendee clause after the status clause:
   ```python
   attendee = first_param(params, "attendee")
   if attendee:
       clauses.append("LOWER(COALESCE(attendees,'') || ' ' || COALESCE(organizer,'')) LIKE ?")
       values.append(f"%{attendee.strip().lower()}%")
   ```
3. In `src/health_server.py`, delete the moved definitions and import them with underscore aliases. Do not edit any call site body.
4. Add `"attendee"` to the tuple in `_api_filter_echo`.
5. Create `src/auth/request_auth.py`:
   - `authenticate` reads the token from `Authorization: Bearer`, `X-API-Key`, `X-Admin-Token`, `?token=`, in that order.
   - Admin token branch: skipped entirely when `admin_token` is falsy. Compare with `hmac.compare_digest`.
   - Cookie branch when `allow_cookie` is true: `admin_token` cookie as today, then the `ma_session` cookie through `SessionStore`.
   - User branch: only `Bearer` and `X-API-Key` values go to `UserStore.find_by_api_key`. Open the DB with `connect(db_path)` and close it in a `finally`.
6. Rewrite `_is_authorized` as a wrapper. Keep the method name and the `allow_cookie` keyword so nothing else in the file changes.
7. Add `_require_admin`: returns True when `self.auth_context` is admin, otherwise sends `{"error": "forbidden"}` with 403 and returns False. Wire it into the four `/admin` branches after the existing authorization check.
8. Tests, then `uv run pytest` and `uv run python -m compileall src tests`.

## Todo List

- [x] `src/state/meeting_queries.py` with moved helpers
- [x] Attendee clause in `meeting_filter_sql`
- [x] Aliased imports in `src/health_server.py`, moved definitions deleted
- [x] `attendee` added to `_api_filter_echo`
- [x] `src/auth/request_auth.py`
- [x] `_is_authorized` wrapper and `_require_admin` gate
- [x] `tests/test_request_auth.py`
- [x] Attendee filter cases in `tests/test_public_api.py`
- [x] Full test suite green

## Test Matrix

| Level | Case | Expectation |
|-------|------|-------------|
| Unit | `Authorization: Bearer <ADMIN_TOKEN>` | admin context |
| Unit | `X-API-Key` and `X-Admin-Token` and `?token=` with the admin token | admin context, all three |
| Unit | admin cookie with `allow_cookie=True` and `False` | admin context, then None |
| Unit | `admin_token` unset and an empty header sent | None, never a match |
| Unit | active user API key via Bearer and via `X-API-Key` | user context, `is_admin` False |
| Unit | deactivated user API key | None |
| Unit | revoked or rotated-away API key | None |
| Unit | unknown token | None |
| Unit | user API key with `is_admin=1` | admin context |
| Integration | non-admin key on `/admin/api/meetings` | 403 |
| Integration | non-admin key on `/api/meetings` | 200 |
| Integration | no credentials on `/api/meetings` | 401 |
| Unit | `attendee=a@example.com` filter | only meetings with that attendee |
| Unit | `attendee` matched against the organizer column | meeting returned |
| Unit | `attendee` with different letter case | still matches |
| Unit | filter echo contains `attendee` | present in the response |
| Regression | every existing test in `tests/test_public_api.py` and `tests/test_admin_manual_join.py` | unchanged and green |

Integration cases drive `AdminHandler` through a `ThreadingHTTPServer` bound to port 0 in a fixture, or through a direct handler instantiation with a fake socket. Prefer the real server on port 0, it exercises the actual routing.

## Success Criteria

- `curl -H "Authorization: Bearer $ADMIN_TOKEN" .../api/meetings` behaves exactly as before, byte for byte on the same DB.
- A user API key reads `/api/meetings` and is refused with 403 on any `/admin/api/*` path.
- `GET /api/meetings?attendee=someone@example.com` returns only meetings listing that address, and the address appears under `filters`.
- Existing test suite green with no test deleted or weakened.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Privilege escalation: user key reaches `/admin/api/*` | Med | High | `_require_admin` on all four admin branches plus an integration test per branch |
| Helper move breaks the monkeypatched settings in tests | Med | Med | Moved helpers take arguments only, never call `load_settings` |
| Per-request DB open in the auth path slows the admin UI | Low | Low | DB is only opened when the admin token branch misses |
| `LIKE` attendee filter matches a substring of another address | Med | Low | Accepted, D2 makes this a convenience filter; documented in the README |

## Security Considerations

- Admin token comparison uses `hmac.compare_digest`.
- API keys are matched by hash, never by the plaintext stored anywhere.
- 403 body carries no user detail.
- `/api/*` remains GET only (`src/health_server.py:74` already returns 405 for POST), so cookie auth added in phase 03 carries no CSRF risk.

## Rollback

Revert the commit. Phase 01 tables stay, unused. No data migration to undo.

## Next Steps

Phase 03 turns on the session cookie for `/api/*` and builds the pages. Phase 05 imports `src/state/meeting_queries.py` unchanged.
