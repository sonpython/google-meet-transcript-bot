---
title: "MCP transcript access + multi-user system"
description: "Per-user login and API keys, bot-invite calendar model, and a FastMCP streamable HTTP server exposing transcript tools."
status: completed
priority: P2
effort: 16h
branch: main
tags: [auth, mcp, calendar, sqlite, deployment]
created: 2026-09-04
---

# MCP transcript access + multi-user system

Source of truth for design: `plans/reports/brainstorm-260904-1216-mcp-multi-user-transcript-access.md` (decisions D1-D6, APPROVED). This plan implements it, it does not revisit it.

## Phases

| # | Phase | Effort | Status | Depends on |
|---|-------|--------|--------|------------|
| 01 | [User store and auth core](phase-01-user-store-and-auth-core.md) | 3h | done | - |
| 02 | [API key auth + attendee filter](phase-02-api-key-auth-and-attendee-filter.md) | 2h | done | 01 |
| 03 | [Web login and user pages](phase-03-web-login-and-user-pages.md) | 4h | done | 02 |
| 04 | [Calendar bot-invite switch](phase-04-calendar-bot-invite-switch.md) | 1.5h | done | - |
| 05 | [MCP server and tools](phase-05-mcp-server-and-tools.md) | 3h | done | 01, 02 |
| 06 | [Deployment wiring and docs](phase-06-deployment-wiring-and-docs.md) | 2h | done (deploy verified; calendar OAuth re-run pending, user action) | 03, 04, 05 |

Phase 04 is independent of 01-03 by data flow but touches `src/health_server.py` (2 lines), so run it either before 02 or after 03, never concurrently with them.

## Dependency graph

```
01 user store ──┬── 02 REST auth ── 03 web UI ──┐
                └── 05 MCP server ──────────────┼── 06 deploy
04 calendar switch ─────────────────────────────┘
```

## File ownership per phase (no overlap when run in order)

- 01: `src/auth/password_hash.py`, `src/auth/api_key.py`, `src/auth/user_store.py`, `src/auth/session_store.py`, `src/state/db.py`
- 02: `src/auth/request_auth.py`, `src/state/meeting_queries.py`, `src/health_server.py` (auth + filter wiring)
- 03: `src/web/*`, `src/health_server.py` (route wiring only)
- 04: `src/calendar_watcher/classifier.py`, `src/main.py`, `src/health_server.py` (2 call sites)
- 05: `src/mcp_server/*`, `pyproject.toml`
- 06: `src/entrypoint.py`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md`, `docs/deployment.md`

## Key locked decisions carried into every phase

- D1 bot-invite calendar: watcher reads BOT_EMAIL's calendar.
- D2 everyone-sees-everything: the `attendee` filter is convenience, never a security boundary.
- D3 remote streamable HTTP MCP with per-user API key in an `Authorization: Bearer` header.
- D4 admin creates users, no self-signup.
- D5 separate MCP process sharing the SQLite file read-only, no FastAPI migration.
- D6 bot joins any meeting it is invited to.

## Hard constraints

- `ADMIN_TOKEN` keeps working everywhere it works today: admin UI cookie login, `/admin/api/*`, `/api/*` via Bearer, `X-API-Key`, `X-Admin-Token`, `?token=`. Verified current behavior at `src/health_server.py:180`.
- New logic lands in new modules. `src/health_server.py` (1176 lines) only gains wiring.
- Python module files stay snake_case because hyphens are not importable. Kebab-case still applies to shell scripts and docs.
- No new heavy dependency beyond the official `mcp` SDK.

## Global risks

| Risk | Likelihood | Impact | Mitigation | Phase |
|------|-----------|--------|------------|-------|
| A non-admin user key reaches `/admin/api/*` | Med | High | Explicit admin gate + test on every `/admin/*` route | 02, 03 |
| Bot-invite cutover silently drops recordings | High | Med | Announce cutover, verify first week, keep old token backup | 04 |
| Two processes on one SQLite file | Low | Med | MCP opens `mode=ro` and never writes, WAL already on | 05 |
| MCP process dies unnoticed | Med | Med | Supervisor restart loop + healthcheck covers 18081 | 06 |

## Unresolved questions

1. Cloudflare tunnel on the host is token-managed (`docs/deployment.md:31-37`), so the `/mcp` path rule is added in the Zero Trust dashboard, not a local `config.yml`. Confirm which one the host actually uses before phase 06.
2. Whether the bot calendar needs the Workspace "automatically add invitations" setting so invites appear without manual accept. Verify during the phase 04 pilot.
