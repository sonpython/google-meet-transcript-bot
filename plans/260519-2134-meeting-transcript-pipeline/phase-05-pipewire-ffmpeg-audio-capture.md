---
phase: 5
title: "PipeWire + FFmpeg Audio Capture"
status: implemented_offline
priority: P1
effort: "2d"
dependencies: []
---

# Phase 5: PipeWire + FFmpeg Audio Capture

## Overview

Provision Proxmox LXC với PipeWire virtual sink + FFmpeg pipeline để capture Chromium audio output thành `.opus` file. Includes Proxmox LXC config + audio passthrough validation.

## Requirements

**Functional:**
- LXC: Debian 12 unprivileged container
- PipeWire user-mode (not system-wide) chạy trong container
- PipeWire Pulse compatibility (`pipewire-pulse`) exposes a virtual sink Chromium can route to
- Chromium audio output piped via PipeWire to FFmpeg
- FFmpeg capture: `meet_capture.monitor → opus @ 32kbps mono`
- Output: `/data/audio/<meet-code>.opus`

**Non-functional:**
- Audio device passthrough configured trong Proxmox host (cgroup + lxc.cgroup2.devices.allow)
- Validate audio capture on container boot (record 2s silence, verify file size > 0)
- Document Proxmox host config in `docs/proxmox-setup.md`

## Architecture

```
[Chromium] → [PipeWire meet_capture (null sink)]
                    │
                    ▼
            [meet_capture.monitor source]
                    │
                    ▼
            [FFmpeg → /data/audio/<code>.opus]
```

## Related Code Files

**Create:**
- `infra/proxmox/lxc-config.conf` (LXC config snippet với audio passthrough)
- `infra/scripts/setup-lxc.sh` (PipeWire + FFmpeg install + config)
- `infra/scripts/audio-healthcheck.sh` (boot-time validation)
- `src/bot/audio_recorder.py` (Python wrapper for FFmpeg subprocess)
- `docs/proxmox-setup.md`

**Modify:**
- `src/bot/browser_session.py` (configure Chromium audio output env: `PULSE_SINK=meet_capture` through `pipewire-pulse`)

## Implementation Steps

1. **Proxmox host config:**
   - Verify `/dev/snd/*` exists trên host
   - LXC config additions:
     ```
     lxc.cgroup2.devices.allow: c 116:* rwm
     lxc.mount.entry: /dev/snd dev/snd none bind,optional,create=dir
     ```
2. **LXC provisioning script (`setup-lxc.sh`):**
   ```bash
   apt install -y pipewire pipewire-pulse wireplumber pipewire-audio-client-libraries ffmpeg
   systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
   pactl load-module module-null-sink sink_name=meet_capture sink_properties=device.description=MeetCapture
   ```
3. **Persistent PipeWire Pulse config:** `/etc/pipewire/pipewire-pulse.conf.d/meet-capture.conf`:
   ```
   pulse.cmd = [
     { cmd = "load-module" args = "module-null-sink sink_name=meet_capture sink_properties=device.description=MeetCapture" flags = [ ] }
   ]
   ```
4. `audio_recorder.py`:
   - `class AudioRecorder`:
     - `start(meet_code) -> path`: spawn FFmpeg subprocess
       ```
       ffmpeg -y -f pulse -i meet_capture.monitor \
              -ac 1 -ar 16000 -c:a libopus -b:a 32k \
              /data/audio/<code>.opus
       ```
     - `stop() -> path`: SIGINT FFmpeg, await flush, return file path
     - `is_running() -> bool`
5. `browser_session.py` env: set `PULSE_SINK=meet_capture` when launching Chromium → audio routes to the PipeWire-backed virtual sink
6. **Audio healthcheck script:**
   - On container boot: record 2s từ meet_capture.monitor, verify `.opus` size > 1KB → log OK or fail
   - Wired into systemd unit ExecStartPre
7. **Test:**
   - Play test audio in Chromium (YouTube), verify recording captures sound

## Success Criteria

- [ ] LXC starts với audio passthrough OK
- [ ] PipeWire meet_capture visible (`pactl list sinks short` or `wpctl status` shows it)
- [ ] Chromium audio output goes to meet_capture (verify với `pactl list sink-inputs` or `wpctl status`)
- [ ] FFmpeg recording produces valid `.opus` file (>1KB, plays back)
- [ ] 30-min recording stress test: file completes, no dropouts
- [ ] `audio-healthcheck.sh` passes on boot

## Risk Assessment

- **LXC audio passthrough complexity (High):** unprivileged LXC + audio is fiddly. Mitigation: detailed doc, fallback to privileged LXC if blocked
- **PipeWire in container quirks:** prefer user mode with `pipewire-pulse`; document system-mode fallback only if user services fail
- **Chromium not routing to meet_capture:** verify `PULSE_SINK` env propagates to subprocess. Fallback: `pactl move-sink-input` post-launch
- **Disk I/O:** 1h opus @ 32kbps = ~14MB. Trivial. But /data should be on persistent storage (not tmpfs)
- **Audio device shared with host:** if Proxmox host uses audio, conflict possible. Document
