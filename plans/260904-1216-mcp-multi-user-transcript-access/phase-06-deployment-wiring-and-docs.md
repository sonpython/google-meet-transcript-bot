# Phase 06 - Deployment wiring and docs

## Context Links

- Design: brainstorm Phase C deployment bullets and risk 4 and 5
- Process start: `src/entrypoint.py:53` (`run`), health thread at `:54`, optional subsystem pattern at `src/runtime_audio.py:12`
- Container: `Dockerfile:21-23`, `docker-compose.yml:28-40`
- Tunnel and host runbook: `docs/deployment.md:25-37`, `docs/deployment.md:39-48`
- Env template: `.env.example`
- API docs to extend: `README.md:77-102`, runtime flow at `README.md:117-127`

## Overview

- Priority: P2
- Status: code done, deploy pending
- Effort: 2h
- Starts and supervises the MCP process inside the existing container, publishes 18081 on the host loopback, adds the tunnel route, and updates every doc the change touches.

## Key Insights

- `entrypoint.run()` already starts the health server in a daemon thread and then blocks on `asyncio.run(main())` (`src/entrypoint.py:54-61`). A supervised subprocess started before that call gives the failure isolation D5 asks for without a new supervisor image.
- The optional-subsystem convention already exists as `start_virtual_audio_if_enabled()` gated by an env var (`src/runtime_audio.py:12-13`). The MCP starter mirrors it exactly, which keeps the entrypoint diff at two lines.
- The health server binds `0.0.0.0:8080` inside the container and the port is published as `127.0.0.1:18080` (`docker-compose.yml:29`). The MCP process needs the same shape: bind `0.0.0.0:18081` inside, publish `127.0.0.1:18081` outside, because cloudflared runs on the host with host networking (`docs/deployment.md:31-37`).
- The container can start degraded and sit in `_hold_degraded` forever (`src/entrypoint.py:47-58`). Start the MCP process before that check so transcript access keeps working while calendar credentials are missing.
- The healthcheck currently probes `/healthz` only (`docker-compose.yml:37`). A dead MCP process would go unnoticed, so the probe must cover both ports. Probe MCP with a TCP connect, because `GET /mcp` without MCP headers is expected to answer with an error status.
- Files must be baked into the image, not copied into a running container. `Dockerfile:14-15` copies `src` and `scripts`, so a rebuild is required, and the deploy command in `docs/deployment.md:44-48` already does `--build`.

## Requirements

Functional:
- The MCP process starts with the container and restarts within seconds if it exits.
- `MCP_ENABLED=false` disables it cleanly, for local runs and for a fast rollback.
- The tunnel serves `/mcp` from 18081 and everything else from 18080 on the same hostname.
- The container is unhealthy when either port is down.

Non-functional:
- No new base image package, no supervisor binary.
- Docs updated in the same commit as the wiring.

## Architecture

```
container
 ├─ thread   health server        0.0.0.0:8080  ─ published ─> host 127.0.0.1:18080
 ├─ process  python -m src.mcp_server  0.0.0.0:18081 ─ published ─> host 127.0.0.1:18081
 │    └─ supervisor thread restarts it after a 5 second backoff
 └─ main     bot loop

host cloudflared
 ├─ meet-assistant.sonpython.com  path ^/mcp  ─> http://localhost:18081
 └─ meet-assistant.sonpython.com  catch all   ─> http://localhost:18080
```

## Related Code Files

Create:
- `src/mcp_server/supervisor.py` - `start_mcp_server_if_enabled()`. Returns immediately when `MCP_ENABLED` is not `true`. Otherwise spawns `subprocess.Popen([sys.executable, "-m", "src.mcp_server"])` and a daemon thread that waits on the child, logs the exit code through `structlog`, sleeps 5 seconds, and respawns. Under 80 lines.

Modify:
- `src/entrypoint.py` - import and call `start_mcp_server_if_enabled()` right after the health thread start at `:54`, before `_missing_runtime_inputs()`.
- `Dockerfile` - `EXPOSE 8080 18081`.
- `docker-compose.yml` - add `"127.0.0.1:18081:18081"` to `ports`, add `MCP_ENABLED: "true"`, `MCP_HOST: 0.0.0.0`, `MCP_PORT: "18081"` to `environment`, and extend the healthcheck to probe both ports.
- `.env.example` - `MCP_ENABLED`, `MCP_HOST`, `MCP_PORT` with comments.
- `README.md` - a Multi-user access section (admin creates users, `/login`, one-time API key) and an MCP section (client config, tool list, everyone-sees-everything note). Update the runtime flow line that still says the watcher matches `USER_EMAIL` (`README.md:119`).
- `docs/deployment.md` - the tunnel path rule, the second published port, the calendar OAuth re-run as `BOT_EMAIL`, and the first-admin bootstrap.

Tests:
- `tests/test_mcp_supervisor.py`

## Implementation Steps

1. Write `src/mcp_server/supervisor.py` with the env gate, the spawn, and the restart thread. Keep a module level handle so a second call is a no-op.
2. Wire it into `src/entrypoint.py` after the health server thread and before the degraded hold.
3. `Dockerfile`: `EXPOSE 8080 18081`.
4. `docker-compose.yml`: publish the port, add the three env vars, replace the healthcheck test with a single python command that opens `/healthz` and then a TCP socket to `127.0.0.1:18081`, failing on either.
5. `.env.example`: document the three variables and note that `USER_EMAIL` is now only the seed admin and the default attendee filter.
6. README updates:
   - Multi-user access: admin opens `/admin/users`, creates a user with a temp password, hands over the temp password and the one-time API key. The user logs in at `/login`, changes the password at `/app`, and reads any meeting. All transcripts are visible to every account, the attendee filter is convenience only.
   - REST: the per-user API key works everywhere `ADMIN_TOKEN` works on `/api/*`, and the new `attendee` filter.
   - MCP: URL `https://<host>/mcp`, `Authorization: Bearer <personal api key>`, the four tools, and a client config snippet.
   - Runtime flow: the watcher now finds Meet events on the bot calendar.
7. `docs/deployment.md` updates:
   - New port line next to the existing `127.0.0.1:18080` entry.
   - Tunnel routing, both the config file form and the dashboard form, since the host tunnel is token-managed:
     ```yaml
     ingress:
       - hostname: meet-assistant.sonpython.com
         path: ^/mcp
         service: http://localhost:18081
       - hostname: meet-assistant.sonpython.com
         service: http://localhost:18080
       - service: http_status:404
     ```
     For a token-managed tunnel, add the same rule as a Public Hostname with a path in the Zero Trust dashboard, ordered before the catch all.
   - Cutover runbook: back up `data/tokens/user-token.fernet`, re-run the calendar OAuth as `BOT_EMAIL`, rebuild, restart, verify upcoming events, announce to the team.
   - First admin bootstrap: `USER_EMAIL` is seeded as an admin row with no password; the operator sets a password from `/admin/users` while authenticated with `ADMIN_TOKEN`.
8. Deploy per `docs/deployment.md:44-48`, then run the smoke checks below.
9. Docs impact: major. `README.md` and `docs/deployment.md` are both updated in this phase.

## Todo List

- [x] `src/mcp_server/supervisor.py`
- [x] `src/entrypoint.py` wiring
- [x] `Dockerfile` expose
- [x] `docker-compose.yml` port, env, healthcheck
- [x] `.env.example`
- [x] `README.md` multi-user, REST, MCP, runtime flow
- [x] `docs/deployment.md` port, tunnel rule, cutover runbook, admin bootstrap
- [x] `tests/test_mcp_supervisor.py`
- [ ] Deploy and run the smoke checks
- [x] Full test suite green

## Test Matrix

| Level | Case | Expectation |
|-------|------|-------------|
| Unit | `MCP_ENABLED` unset or false | no process spawned, returns immediately |
| Unit | `MCP_ENABLED=true` with a stub command | child spawned once |
| Unit | child exits | supervisor logs and respawns after the backoff |
| Unit | called twice | second call is a no-op, no duplicate child |
| Smoke on host | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/healthz` | 200 |
| Smoke on host | TCP connect to `127.0.0.1:18081` | open |
| Smoke on host | `curl -X POST http://127.0.0.1:18081/mcp` with no key | 401 |
| Smoke on host | `curl -H "Authorization: Bearer $ADMIN_TOKEN" https://<host>/api/meetings?limit=1` | 200, unchanged from before the deploy |
| Smoke on host | `https://<host>/mcp` from Claude Desktop with a user key | tools listed, transcript returned |
| Smoke on host | `docker compose ps` after killing the MCP child | container healthy again within about 30 seconds |
| Smoke on host | `/admin` with `ADMIN_TOKEN` | dashboard unchanged |

The supervisor unit test uses a real short-lived child command such as `sys.executable -c "pass"`, not a mock, so the restart path is genuinely exercised.

## Success Criteria

- Both ports answer on the host after a single `docker compose up -d --build`.
- The tunnel serves the admin UI and `/mcp` on the same hostname.
- Killing the MCP child inside the container brings it back automatically and the healthcheck recovers.
- Every acceptance item in the design's success criteria passes end to end: user login, filtering, REST with a personal key, MCP from a desktop client, bot joining a meeting it was invited to, and unchanged `ADMIN_TOKEN` flows.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Tunnel path rule ordering sends `/mcp` to 18080 | Med | Med | Path rule listed before the catch all, verified with curl through the public hostname |
| Token-managed tunnel means the config file edit does nothing | Med | Med | Documented both forms, confirm which one the host uses before editing, listed as an open question |
| MCP child crash-loops and floods the log | Low | Low | 5 second backoff and one log line per exit |
| New port exposed beyond loopback | Low | High | Publish as `127.0.0.1:18081:18081`, never a bare port mapping |
| Healthcheck flaps during the MCP restart window | Med | Low | Existing 3 retries at a 30 second interval covers a 5 second respawn |
| New files not baked into the image | Med | Med | Deploy uses `--build`, never `docker cp` |

## Security Considerations

- 18081 is published on the host loopback only, so the tunnel is the single ingress path.
- TLS terminates at cloudflared, so cookies stay non-Secure by design; the docs state that the service must never be exposed directly.
- `ADMIN_TOKEN` remains a full admin credential and must not be handed to regular users now that per-user keys exist. The README says so explicitly.
- No secret is added to any committed file. The three new variables carry no secrets.

## Rollback

Set `MCP_ENABLED=false` and restart to drop the MCP surface in seconds without a rebuild. Remove the tunnel path rule to cut external access even faster. Full rollback is a revert plus a rebuild; the calendar switch from phase 04 rolls back separately with its token backup.

## Next Steps

Announce the bot-invite cutover to the team, then verify recordings daily for the first week per the design risk list.
