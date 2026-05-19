# Deployment

## Platform

Docker Compose on `192.168.1.120`.

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
  | ssh root@192.168.1.120 'mkdir -p /opt/meeting-assistant && tar xzf - -C /opt/meeting-assistant'

ssh root@192.168.1.120 'cd /opt/meeting-assistant && docker compose up -d --build meeting-assistant'
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
ssh root@192.168.1.120
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
