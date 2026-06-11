#!/usr/bin/env bash
# Sync the repo to the Docker host and rebuild the meeting-assistant container.
# Mirrors the Deploy Command documented in docs/deployment.md.
set -euo pipefail

HOST="${DEPLOY_HOST:-root@192.168.1.120}"
DEST="${DEPLOY_PATH:-/opt/meeting-assistant}"

cd "$(dirname "$0")/.."

tar --exclude-vcs \
  --exclude='.venv' \
  --exclude='.uv' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='data' \
  --exclude='.env' \
  --exclude='client_secrets.json' \
  -czf - . | ssh "$HOST" "mkdir -p $DEST && tar xzf - -C $DEST"

ssh "$HOST" "cd $DEST && docker compose up -d --build meeting-assistant"
