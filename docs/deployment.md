# Deployment

## Platform

Docker Compose on `192.168.1.160` (root SSH). The IP is DHCP-assigned and has
moved before (was `192.168.1.120`). If it is unreachable, the box likely took a
new lease: the service binds `127.0.0.1:18080` so it is invisible to LAN port
scans — find it by SSHing candidate hosts and checking for `/opt/meeting-assistant`
(e.g. `docker ps | grep meeting-assistant`).

## Host Path

```bash
/opt/meeting-assistant
```

## Runtime URL

The container publishes the health/status endpoint on the Docker host only:

```text
http://127.0.0.1:18080/status
```

Cloudflare Tunnel should route:

```text
meet-assistant.sonpython.com -> http://localhost:18080
```

Tunnel runtime on the Docker host:

```text
meeting-assistant-cloudflared
```

Run it with a Cloudflare tunnel token and host networking so it can reach `localhost:18080` on the host. Do not commit the token.

## Deploy Command

From the repository root:

```bash
tar --exclude='.git' --exclude='.venv' --exclude='.uv' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='data' --exclude='.env' --exclude='client_secrets.json' -czf - . \
  | ssh root@192.168.1.160 'mkdir -p /opt/meeting-assistant && tar xzf - -C /opt/meeting-assistant'

ssh root@192.168.1.160 'cd /opt/meeting-assistant && docker compose up -d --build meeting-assistant'
```

## Current Status

Deployed container:

```text
meeting-assistant -> 127.0.0.1:18080:8080
```

The service can start in degraded mode while secrets are missing. `/status` reports missing runtime inputs. As of the first Docker host deploy, Gemini, Telegram, and generated passphrases were populated from local Claude memory/env; the remaining required input is the real Google OAuth client secret JSON.

## Required Host Files

Do not commit these files. Put them directly on the host:

```text
/opt/meeting-assistant/.env
/opt/meeting-assistant/secrets/client_secrets.json
/opt/meeting-assistant/data/tokens/user-token.fernet
/opt/meeting-assistant/data/tokens/storage-state.fernet
```

## Host Commands

```bash
ssh root@192.168.1.160
cd /opt/meeting-assistant
docker compose ps
docker compose logs -f meeting-assistant
curl http://127.0.0.1:18080/status
docker compose restart meeting-assistant
```

## Next Runtime Steps

1. Fill `/opt/meeting-assistant/.env` with real values.
2. Replace `/opt/meeting-assistant/secrets/client_secrets.json` with the Google OAuth Desktop client JSON.
3. Run Calendar OAuth and bot login in an interactive environment to generate encrypted token files.
4. Restart the service.
5. Map Cloudflare Tunnel for `meet-assistant.sonpython.com` to `http://localhost:18080`.

## Bot Google Session Re-Auth

The keepalive reopens the persistent Chromium profile (`BOT_USER_DATA_DIR`)
headless every 15 minutes so cookies rotate naturally like a real user - it
never types a password. The Workspace edition has no Google session control
(Business Plus+ only), so the web session hard-expires 14 days after the last
authentication regardless of keepalive activity.

### Automatic self-heal (primary path)

Root's crontab on the Docker host runs `scripts/bot-session-auto-relogin.sh`
daily at 21:30 UTC (04:30 Asia/Saigon):

- Session still valid: the login script reaches myaccount without typing a
  password (no-op, refreshes the storageState snapshot).
- Session expired: it performs the single password login that restores it -
  once per ~14 days, from the host's own residential IP.
- Three failed attempts (60s apart, covers keepalive profile-lock collisions):
  Telegram alert, human takes over. Log: `/opt/meeting-assistant/data/auto-relogin.log`.

### Manual recovery (when the cron alert fires)

Log in **in-container** so cookies are device-bound to the host - never push a
Mac-created profile or storageState snapshot to the host (device-bound cookies
such as LSID/SIDCC/PSIDTS do not survive the transplant and the container ends
up fully signed out):

```bash
ssh root@192.168.1.160 "docker exec -e PYTHONPATH=/app meeting-assistant \
  xvfb-run -a python scripts/bot_persistent_login.py --auto-password --timeout-minutes 8"
```

If that hits a Google challenge, first lower the account risk score with a
headed login from a workstation on the same home network (throwaway local
profile; secrets loaded literally from a copy of the host `.env` - do not
ssh-command-substitute `STORAGE_PASSPHRASE`, terminal escapes corrupt it):

```bash
PYTHONPATH=. STORAGE_PASSPHRASE=... BOT_EMAIL=... BOT_PASSWORD=... \
  uv run python scripts/bot_persistent_login.py --auto-password \
    --user-data-dir /tmp/mac-bot-profile --out /tmp/mac-storage-state.fernet
```

then re-run the in-container command; password-only login passes once the risk
score drops. Verify with `bot_session_keepalive_ok` in container logs. Backup
before recovery attempts:

```bash
ssh root@192.168.1.160 "cd /opt/meeting-assistant/data && \
  cp tokens/storage-state.fernet tokens/storage-state.fernet.bak-$(date +%y%m%d) && \
  tar czf bot-profile.bak-$(date +%y%m%d).tgz bot-profile"
```

### Version pin

`pyproject.toml` pins `playwright==1.60.0` to match the Dockerfile base image
`mcr.microsoft.com/playwright/python:v1.60.0-noble`. Bump both together - a
floating `>=` pin once pulled 1.61.0 into a v1.60.0 image and Chromium could
not launch after the next container recreate.
