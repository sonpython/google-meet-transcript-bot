import os
import subprocess
import time
from pathlib import Path

import structlog


def start_virtual_audio_if_enabled() -> None:
    if os.getenv("ENABLE_VIRTUAL_AUDIO", "false").lower() != "true":
        return
    log = structlog.get_logger(__name__)
    _start_xvfb(log)
    _start_pulseaudio(log)
    _ensure_null_sink(log)
    os.environ.setdefault("PULSE_SINK", "meet_capture")


def _start_xvfb(log) -> None:
    display = os.getenv("DISPLAY", ":99")
    display_number = display.removeprefix(":").split(".")[0]
    lock_path = Path(f"/tmp/.X{display_number}-lock")
    socket_path = Path(f"/tmp/.X11-unix/X{display_number}")
    lock_path.unlink(missing_ok=True)
    socket_path.unlink(missing_ok=True)

    stderr_path = Path("/tmp/meeting-assistant-xvfb.log")
    stderr = stderr_path.open("ab")
    process = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1366x768x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=stderr,
        start_new_session=True,
    )
    os.environ["DISPLAY"] = display
    time.sleep(1)
    if process.poll() is not None:
        stderr.close()
        message = stderr_path.read_text(errors="replace")[-2000:] if stderr_path.exists() else ""
        raise RuntimeError(f"Xvfb failed to start on {display}: {message.strip()}")
    log.info("xvfb_started", display=display, pid=process.pid)


def _start_pulseaudio(log) -> None:
    runtime_path = Path("/tmp/meeting-assistant-pulse")
    runtime_path.mkdir(mode=0o700, exist_ok=True)
    socket_path = runtime_path / "native"
    socket_path.unlink(missing_ok=True)
    os.environ["PULSE_SERVER"] = f"unix:{socket_path}"

    config_path = runtime_path / "default.pa"
    config_path.write_text(
        "\n".join(
            [
                f"load-module module-native-protocol-unix socket={socket_path} auth-anonymous=1",
                "load-module module-null-sink sink_name=meet_capture sink_properties=device.description=MeetCapture",
                "set-default-sink meet_capture",
                "set-default-source meet_capture.monitor",
                "",
            ]
        )
    )

    stderr_path = Path("/tmp/meeting-assistant-pulseaudio.log")
    stderr = stderr_path.open("ab")
    process = subprocess.Popen(
        ["pulseaudio", "--daemonize=no", "--exit-idle-time=-1", "--disallow-exit", "-n", "-F", str(config_path)],
        stdout=subprocess.DEVNULL,
        stderr=stderr,
        start_new_session=True,
    )
    time.sleep(1)
    if process.poll() is not None:
        stderr.close()
        message = stderr_path.read_text(errors="replace")[-2000:] if stderr_path.exists() else ""
        raise RuntimeError(f"PulseAudio failed to start: {message.strip()}")
    log.info("pulseaudio_started", pid=process.pid)


def _ensure_null_sink(log) -> None:
    sources = subprocess.run(
        ["pactl", "list", "short", "sources"],
        text=True,
        capture_output=True,
        check=False,
    )
    if "meet_capture.monitor" in sources.stdout:
        log.info("pulseaudio_null_sink_ready", source="meet_capture.monitor")
        return
    raise RuntimeError(f"PulseAudio null sink missing: {sources.stderr.strip() or sources.stdout.strip()}")
