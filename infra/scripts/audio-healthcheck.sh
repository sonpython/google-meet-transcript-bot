#!/usr/bin/env bash
set -euo pipefail

OUT="${TMPDIR:-/tmp}/meeting-assistant-audio-healthcheck.opus"
ffmpeg -y -f pulse -i meet_capture.monitor -t 2 -ac 1 -ar 16000 -c:a libopus -b:a 32k "$OUT" >/dev/null 2>&1
test -s "$OUT"
rm -f "$OUT"
