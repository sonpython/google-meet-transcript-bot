#!/usr/bin/env bash
set -euo pipefail

install -m 0644 infra/systemd/meeting-assistant.service /etc/systemd/system/meeting-assistant.service
systemctl daemon-reload
systemctl enable --now meeting-assistant.service
