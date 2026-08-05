#!/usr/bin/env bash
# Daily self-heal for the bot Google web session, run from root's crontab on
# the Docker host. The Workspace edition has no Google session control, so the
# session hard-expires 14 days after the last authentication no matter how warm
# the keepalive keeps the profile.
#
# While the session is still valid, the login script reaches myaccount without
# ever typing a password (a harmless no-op that also refreshes the storageState
# snapshot). Right after expiry it performs the single password login that
# restores the session - once per ~14 days, from the host's own residential IP,
# which keeps the account risk score untouched. Alerts Telegram when all
# attempts fail so a human can run the manual procedure.
set -uo pipefail

APP_DIR="/opt/meeting-assistant"
LOG="$APP_DIR/data/auto-relogin.log"
CONTAINER="meeting-assistant"

log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" >>"$LOG"; }

alert() {
  local token chat
  token=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$APP_DIR/.env" | cut -d= -f2-)
  chat=$(grep -E '^TELEGRAM_CHAT_ID=' "$APP_DIR/.env" | cut -d= -f2-)
  if [ -n "$token" ] && [ -n "$chat" ]; then
    curl -fsS -m 10 "https://api.telegram.org/bot${token}/sendMessage" \
      -d chat_id="${chat}" -d text="$1" >/dev/null 2>&1 || true
  fi
}

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  log "container not running; skip"
  alert "ALERT: bot session auto-relogin skipped: ${CONTAINER} container not running"
  exit 1
fi

# The keepalive briefly holds the Chromium profile lock every 15 minutes;
# retry instead of failing on that collision.
for attempt in 1 2 3; do
  if docker exec -e PYTHONPATH=/app "$CONTAINER" \
    xvfb-run -a python scripts/bot_persistent_login.py --auto-password --timeout-minutes 8 \
    >>"$LOG" 2>&1; then
    log "attempt ${attempt}: session ok"
    exit 0
  fi
  log "attempt ${attempt} failed; retrying in 60s"
  sleep 60
done

log "all 3 attempts failed"
alert "ALERT: bot session auto-relogin failed 3 attempts: manual relogin required"
exit 1
