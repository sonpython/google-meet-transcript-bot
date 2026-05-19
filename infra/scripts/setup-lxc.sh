#!/usr/bin/env bash
set -euo pipefail

apt-get update
apt-get install -y python3.12 python3.12-venv ffmpeg pipewire pipewire-pulse wireplumber pipewire-audio-client-libraries
systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service || true
pactl load-module module-null-sink sink_name=meet_capture sink_properties=device.description=MeetCapture || true
