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

The keepalive keeps the bot logged in by reopening a persistent Chromium
profile (`BOT_USER_DATA_DIR`) headless every few minutes, so cookies/session
keys rotate naturally like a real user — it never types a password. A signed-out
profile (e.g. policy-forced logout) cannot self-recover; the keepalive job sends
a Telegram/Discord alert and waits for a human to re-run the one-time login.

To restore the session from a workstation:

```bash
# 1. Headed login into a fresh persistent profile + storageState snapshot.
#    Get STORAGE_PASSPHRASE from /opt/meeting-assistant/.env on the host.
#    Beware: command substitution over ssh can capture terminal escape
#    sequences from the host shell — copy the value manually if unsure.
STORAGE_PASSPHRASE=... PYTHONPATH=. \
  uv run python scripts/bot_persistent_login.py \
    --user-data-dir /tmp/bot-profile \
    --out /tmp/storage-state.fernet \
    --expected-email "$BOT_EMAIL"

# 2. Deploy and recreate (restart alone can leave a stale PulseAudio pid file).
ssh root@192.168.1.160 "cp /opt/meeting-assistant/data/tokens/storage-state.fernet /opt/meeting-assistant/data/tokens/storage-state.fernet.bak"
ssh root@192.168.1.160 "rm -rf /opt/meeting-assistant/data/bot-profile"
scp /tmp/storage-state.fernet root@192.168.1.160:/opt/meeting-assistant/data/tokens/storage-state.fernet
scp -r /tmp/bot-profile root@192.168.1.160:/opt/meeting-assistant/data/bot-profile
ssh root@192.168.1.160 "cd /opt/meeting-assistant && docker compose up -d --force-recreate meeting-assistant"

# 3. Verify: wait for bot_session_keepalive_ok in logs.
```

A persistent profile is somewhat OS/Chromium-version specific. If a profile
created on a macOS workstation misbehaves on the Linux host, run
`bot_persistent_login.py` on the host itself (headed X/VNC session) so the
profile is created in the same environment that later opens it headless. The
storageState snapshot (`--out`) is cross-platform and always feeds the meeting
flow regardless.

Permanent fix: in Google Admin console (Security → Google session control),
set the bot account's OU web session duration to "Session never expires" so
the 14-day expiry stops logging the bot out.
