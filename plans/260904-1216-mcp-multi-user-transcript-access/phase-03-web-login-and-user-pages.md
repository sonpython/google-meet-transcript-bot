# Phase 03 - Web login and user pages

## Context Links

- Design: brainstorm Phase A bullets 4, 5, 6 (user login, read-only UI, admin user management, password change)
- Existing cookie login: `src/health_server.py:79` (`_handle_login`), `:91` (`_handle_logout`), cookie set at `:86` with `Path=/admin`
- Existing page renderers: `_login_html` `src/health_server.py:1005`, `_admin_html` `:1015`, `_settings_html` `:1026`, `_style` `:1037`, `_script` `:1054`
- Public API used by the new page: `_api_list_meetings` `src/health_server.py:289`, `_api_meeting_detail` `:302`
- Auth from phase 02: `src/auth/request_auth.py`

## Overview

- Priority: P2
- Status: done
- Effort: 4h
- Adds `/login`, `/logout-user`, `/app`, `/account/password` for regular users, and `/admin/users` plus `/admin/api/users*` for admins. The existing `/admin` token login and dashboard stay exactly as they are.

## Key Insights

- The admin cookie is scoped `Path=/admin` (`src/health_server.py:86`), so it is never sent to `/api/*` or `/app`. The user session cookie must be `Path=/` to work on both `/app` and `/api/*`.
- The read-only user page can consume the existing `/api/meetings` and `/api/meetings/{code}` endpoints, so no second query layer is needed. This is why phase 02 comes first, and why `/api/*` flips to `allow_cookie=True` here.
- `/api/*` is GET only (`src/health_server.py:74`), so cookie auth adds no CSRF exposure on that surface. The mutating routes added here are `/admin/api/users*` and `/account/password`, which are POST and require either the admin token or a valid session.
- `_style()` is needed by both the existing admin pages and the new user pages. Extracting it into `src/web/styles.py` avoids a circular import and avoids duplicating 15 lines of CSS.
- Everyone sees everything (D2). The user page shows all meetings with an attendee filter box prefilled with the logged-in user's email, and no delete, rejoin, regenerate, or force-out controls.

## Requirements

Functional:
- `GET /login` renders an email and password form. `POST /login` sets `ma_session` on success, re-renders with an error on failure.
- `POST /logout-user` clears the cookie and deletes the session row.
- `GET /app` requires a session, renders the read-only history and detail view with `q`, `from`, `to`, `attendee` filters.
- `POST /account/password` changes the caller's own password after checking the current one, then deletes all other sessions for that user.
- `GET /admin/users` renders the admin user management page.
- `/admin/api/users` endpoints: list, create, set password, rotate API key, revoke API key, set active. All admin only.
- A created API key is shown exactly once in the admin UI response.

Non-functional:
- `src/health_server.py` grows by wiring only, roughly 25 lines across `do_GET` and `do_POST`.
- Each new module under 200 lines.

## Architecture

```
browser ── GET  /login  ─────────────> user_routes.handle -> user_pages.login_html
browser ── POST /login  ─────────────> UserStore.verify_login -> SessionStore.create -> Set-Cookie ma_session (Path=/, HttpOnly, SameSite=Lax)
browser ── GET  /app    ── cookie ───> user_pages.app_html
  page JS ─ GET /api/meetings?...  ── cookie ─> existing _api_list_meetings
  page JS ─ GET /api/meetings/{code} ─ cookie ─> existing _api_meeting_detail
admin  ── GET  /admin/users ── admin ─> admin_users.page_html
admin  ── POST /admin/api/users/... ─> UserStore mutations
```

Route dispatch contract, so `health_server` stays a router:

```python
# src/web/user_routes.py
@dataclass(frozen=True)
class WebResponse:
    status: int
    content_type: str
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()

def handle(method: str, path: str, query: dict, headers: dict, body: bytes, ctx) -> WebResponse | None
```

`health_server` calls `handle(...)`, and when the result is not `None` it writes the response. `None` means the path is not ours, fall through to the existing routing.

## Related Code Files

Create:
- `src/web/__init__.py`
- `src/web/styles.py` - the CSS string moved from `_style()` plus a small addition for the user page.
- `src/web/user_pages.py` - `login_html(error="")`, `app_html(user_email)`. Compact HTML plus inline JS in the existing style.
- `src/web/user_routes.py` - `WebResponse`, `handle(...)` for `/login`, `/logout-user`, `/app`, `/account/password`.
- `src/web/admin_users.py` - `page_html()` and the JSON handlers `list_users`, `create_user`, `set_password`, `rotate_key`, `revoke_key`, `set_active`.

Modify:
- `src/health_server.py`
  - `_style()` returns `src.web.styles.CSS` so the admin pages are unchanged.
  - `do_GET`: call `handle(...)` before the `/admin` branch; `/admin/users` renders `admin_users.page_html()` behind `_require_admin`.
  - `do_POST`: same dispatch, and route `/admin/api/users...` into `admin_users` handlers from `_handle_api_post`.
  - `/api/*` branch at `:52`: pass `allow_cookie=True`.

Tests:
- `tests/test_user_routes.py`, `tests/test_admin_users_api.py`

## Implementation Steps

1. Create `src/web/styles.py` holding the CSS currently returned by `_style()`. Point `_style()` at it. Run the suite to confirm the admin pages are untouched.
2. Create `src/web/user_pages.py`. `login_html` posts to `/login` with `email` and `password` fields. `app_html` renders a list plus a detail pane, filter inputs for search, date from, date to, attendee, and a password change form posting to `/account/password`. No mutating meeting controls.
3. Create `src/web/user_routes.py` with `WebResponse` and `handle`:
   - `GET /login`: 200 with the form. When the caller already has a session, redirect to `/app`.
   - `POST /login`: parse the form body, `UserStore.verify_login`, on success `SessionStore.create` and `Set-Cookie: ma_session=<token>; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800`, redirect 303 to `/app`. On failure render the form with an error and status 401. Do not reveal whether the email exists.
   - `POST /logout-user`: delete the session row, expire the cookie, redirect to `/login`.
   - `GET /app`: 303 to `/login` when there is no session context.
   - `POST /account/password`: requires a session context, verifies the current password, enforces a minimum length of 10, calls `set_password`, then `delete_for_user` and issues a fresh session for the current browser.
4. Create `src/web/admin_users.py`. Never return `password_hash` or `api_key_hash`. `rotate_key` returns `{"api_key": "<plaintext>"}` once and the page shows a copy control. `set_active(false)` also calls `SessionStore.delete_for_user`.
5. Wire `src/health_server.py`. Keep the changes to routing and response writing only.
6. Flip `/api/*` to `allow_cookie=True` at `src/health_server.py:53`.
7. Tests, then `uv run pytest` and `uv run python -m compileall src tests`.

## Todo List

- [x] `src/web/styles.py` and `_style()` delegation
- [x] `src/web/user_pages.py`
- [x] `src/web/user_routes.py`
- [x] `src/web/admin_users.py`
- [x] `health_server` route wiring for `/login`, `/logout-user`, `/app`, `/account/password`
- [x] `/admin/users` page and `/admin/api/users*` handlers behind `_require_admin`
- [x] `/api/*` accepts the session cookie
- [x] `tests/test_user_routes.py`
- [x] `tests/test_admin_users_api.py`
- [x] Full test suite green

## Test Matrix

| Level | Case | Expectation |
|-------|------|-------------|
| Unit | `POST /login` correct credentials | 303 to `/app`, `Set-Cookie ma_session`, `Path=/`, `HttpOnly` |
| Unit | `POST /login` wrong password, unknown email, inactive user | 401, identical error text in all three |
| Unit | `GET /app` without a cookie | 303 to `/login` |
| Unit | `GET /app` with a valid cookie | 200 containing the user email |
| Unit | `POST /logout-user` | cookie expired, session row gone, later `/app` redirects |
| Unit | `POST /account/password` with a wrong current password | 400, password unchanged |
| Unit | `POST /account/password` success | new password verifies, other sessions invalidated |
| Unit | password shorter than the minimum | 400 |
| Integration | `GET /api/meetings` with only the session cookie | 200 |
| Integration | `GET /admin/api/users` with a non-admin session | 403 |
| Integration | `GET /admin/api/users` with `ADMIN_TOKEN` | 200 |
| Unit | `POST /admin/api/users` create | user exists, response has no hash fields |
| Unit | rotate key twice | first key stops working, response shows the plaintext once |
| Unit | revoke key | key no longer authenticates on `/api/*` |
| Unit | deactivate a user | sessions deleted, API key rejected |
| Regression | `/admin` token login, dashboard, settings page | unchanged and green |

## Success Criteria

- An admin creates a user in `/admin/users`, hands over the temp password, and that user logs in at `/login` and reads any meeting transcript in `/app`.
- The user page exposes no delete, rejoin, force-out, or regenerate control, verified by asserting those strings are absent from the rendered HTML.
- A non-admin session or key gets 403 on every `/admin/*` path.
- `/admin` with `ADMIN_TOKEN` looks and behaves exactly as before.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Session cookie scoped `Path=/` collides with the admin cookie | Low | Med | Different cookie names, `admin_token` stays `Path=/admin` |
| Read-only page leaks a mutating control | Med | Med | Separate template, assert the control strings are absent |
| Admin user endpoints reachable by a plain user | Low | High | `_require_admin` plus per-endpoint tests |
| Page modules grow past 200 lines | Med | Low | Split the JS into `src/web/user_page_script.py` if it happens |
| Session fixation after password change | Low | Med | Delete all sessions on password change and issue a fresh one |

## Security Considerations

- Cookies are `HttpOnly` and `SameSite=Lax`. `Secure` is not set because the container serves plain HTTP behind the tunnel that terminates TLS; note this in the deployment doc.
- Login failures are indistinguishable across wrong password, unknown email, and inactive account.
- No password or API key is ever written to a log line or to an HTML page except the one-time key display.
- Temp passwords are set by the admin and the user is expected to change them; the UI says so.

## Rollback

Revert the commit. Sessions become dead rows, users fall back to `ADMIN_TOKEN` access. `/api/*` returns to header-only auth.

## Next Steps

Phase 06 documents the login flow and the one-time API key handover in the README.
