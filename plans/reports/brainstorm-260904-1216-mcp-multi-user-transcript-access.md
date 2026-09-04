# Brainstorm: MCP transcript access + multi-user system

Date: 2026-09-04. Participants: user (sonpython) + Claude. Status: APPROVED by user.

## Problem statement

Meeting-assistant today is single-user: 1 flat `ADMIN_TOKEN` for admin UI + REST API, calendar watcher reads ONE calendar and qualifies events against the single `USER_EMAIL` (`src/calendar_watcher/classifier.py:8`). Requirements:

1. MCP server so users connect (Claude Desktop/Code, Cursor...) and pull transcripts.
2. Own user/password system. Each user sets their email; bot follows and joins their meetings. Single user tier. Users can view ALL meetings or filter by meetings their email was invited to.

## Current state (scouted)

- API: `src/health_server.py` (1175 lines, stdlib `BaseHTTPRequestHandler`): `GET /api/meetings`, `/api/meetings/{code}`, `/api/transcripts` (Bearer/X-API-Key = ADMIN_TOKEN), `/admin/*` (cookie login with same token).
- DB: SQLite `src/state/db.py`; `meetings` table already has `attendees` TEXT column -> attendee filter possible from existing data. No users concept anywhere.
- Deploy: Docker on 192.168.1.160, service binds 127.0.0.1:18080, exposed via cloudflared tunnel.
- Meeting selection: OAuth calendar of USER_EMAIL, event qualifies if USER_EMAIL organizer/accepted attendee.

## Decisions (user-confirmed 2026-09-04)

| # | Question | Decision |
|---|----------|----------|
| D1 | How bot sees other users' meetings | **Invite the bot**: watcher switches to reading BOT_EMAIL's own calendar; users invite bot email to their events |
| D2 | Visibility model | **Everyone sees everything**; attendee filter is a UI/API convenience, NOT a security boundary. Deliberate decision, transcripts shared org-wide |
| D3 | MCP transport | **Remote streamable HTTP** via cloudflared, per-user API key auth |
| D4 | Account creation | **Admin creates users** in admin UI (no self-signup, no email verification) |
| D5 | Architecture | **PA1: separate FastMCP process** sharing SQLite; NO FastAPI migration (YAGNI, health_server works) |
| D6 | Join policy | **Bot joins ANY meeting it is invited to** (whole domain trusted); registered-user match NOT required |
| D7 | Database | **Keep SQLite** (user asked about Postgres for 15-20 users / 3-4 heavy; rejected as YAGNI). Load is metadata-only reads, content lives in files, single writer. Mitigation: WAL mode + busy_timeout, MCP opens read-only connections. Revisit Postgres only at multi-host / multi-writer / hundreds of users |

## Evaluated approaches

### MCP architecture
- **PA1 (chosen)**: FastMCP (official python `mcp` SDK) as 2nd process in existing container, bind 127.0.0.1:18081, cloudflared adds `/mcp` route. Reads same SQLite (read-only), validates per-user API keys against `users` table. Pros: zero touch on 1175-line prod health_server, MCP SDK needs ASGI anyway, failure isolation. Cons: +1 process, +1 tunnel route.
- PA2 (rejected): migrate whole API to FastAPI, mount MCP in one ASGI app. Cleaner long-term but big regression risk, violates YAGNI now. Revisit as separate project if system grows.
- stdio local package (rejected by user): per-user install/maintenance burden.

### Calendar visibility
- Invite-the-bot (chosen): works cross-domain, no extra OAuth, no admin console changes. Cost: people must remember to invite bot.
- Domain-wide delegation (rejected): needs Super Admin config, same-domain only.
- Per-user OAuth (rejected): heaviest, SaaS-grade effort not needed.

## Final design

### Phase A - user system (foundation; B and C depend on it)
- New `users` table in existing SQLite: `id, email UNIQUE, display_name, password_hash, api_key_hash, is_admin INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1, created_at, updated_at`.
- Password hash: `hashlib.scrypt` (stdlib, no new dep). API key: 32 random bytes, shown once at creation, stored sha256.
- Auth module as NEW files (health_server already over 200-line guideline; do not grow it more than wiring): e.g. `src/auth/user_store.py`, `src/auth/api_key.py`.
- REST `/api/*`: accept per-user API key in addition to ADMIN_TOKEN (backward compat).
- Web: `/login` for regular users (extend existing cookie mechanism); read-only history+transcript UI (no delete/rejoin/regenerate buttons). Admin-only: user management page (create user, temp password, regenerate/revoke API key, deactivate).
- New filter `attendee=<email>` on `/api/meetings` + `/api/transcripts` + web UI (data already in `meetings.attendees`).
- Password change: user can change own password after login.

### Phase B - bot follows invites
- One-time calendar OAuth re-run as BOT_EMAIL account; watcher reads bot's calendar.
- Classifier: event qualifies if it has a Meet link and bot is invited and has not declined (per D6 no registered-user match). Users' "set my email" now only powers the attendee filter/profile, not join gating.
- `USER_EMAIL` config becomes seed: auto-create admin user row for it on first migration.
- Behavior change to document: meetings where bot NOT invited are no longer recorded. Transition: user chose clean cutover (no dual-calendar period).

### Phase C - MCP server
- FastMCP streamable HTTP app, own entrypoint (e.g. `src/mcp_server/`), run by container entrypoint/supervisor next to main process, port 18081.
- Tools: `list_meetings(from, to, query, attendee, status, limit)`, `get_meeting(meet_code)` (metadata+summary+minutes), `get_transcript(meet_code)`, `search_transcripts(query, from, to, attendee, limit)`.
- Auth: `Authorization: Bearer <personal api key>` validated against `users` (active only). ADMIN_TOKEN also accepted.
- Cloudflared config: route `<host>/mcp` -> 127.0.0.1:18081.
- SQLite from 2 processes: MCP opens read-only connections (`mode=ro`) + WAL already/if needed; MCP never writes.

## Risks

1. claude.ai web custom connectors expect OAuth; Bearer header works for Claude Desktop/Code/Cursor. If web need arises, add pragmatic `/mcp/<api_key>` path variant later (deferred, YAGNI).
2. Bot-invite cutover: silent loss of recordings for non-invited meetings. Mitigate: announce to team, verify first week.
3. Everyone-sees-everything is a deliberate user decision (D2); revisit only if user asks.
4. 2-process container: entrypoint must supervise both, healthcheck should cover MCP too.
5. Cron/image-baked scripts precedent: remember new files must land in Docker image (rebuild) not just docker cp.

## Success criteria

- User created by admin can: login web, view/filter all meetings, use API key on REST and on MCP from Claude Desktop.
- Bot joins a meeting solely because bot email was invited (no code change per user).
- Existing ADMIN_TOKEN flows unchanged (admin UI, meet.sh helper, rejoin endpoint).
- All tests pass; new unit tests for user store, api-key auth, classifier, MCP tool handlers.

## Next steps

- Planner creates implementation plan at `plans/260904-1216-mcp-multi-user-transcript-access/` with phases A/B/C above.

## Unresolved questions

- Exact cloudflared ingress config on host (verify current `config.yml` before Phase C deploy).
- Whether bot calendar auto-accept invites needs a Workspace calendar setting tweak (verify during Phase B pilot).
