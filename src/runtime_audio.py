import os
import re
import subprocess
import time
from pathlib import Path

import structlog

SESSION_SINK_PREFIX = "meet_capture_"


def start_virtual_audio_if_enabled() -> None:
    if os.getenv("ENABLE_VIRTUAL_AUDIO", "false").lower() != "true":
        return
    log = structlog.get_logger(__name__)
    _start_xvfb(log)
    _start_pulseaudio(log)
    cleanup_stale_session_sinks(log)
    _ensure_null_sink(log)
    os.environ.setdefault("PULSE_SINK", "meet_capture")


def safe_session_sink_name(meet_code: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", meet_code.lower()).strip("_")
    if not slug:
        raise ValueError("meet_code cannot produce a safe PulseAudio sink name")
    return f"{SESSION_SINK_PREFIX}{slug}"


def create_session_sink(sink_name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_]+", sink_name):
        raise ValueError(f"unsafe PulseAudio sink name: {sink_name}")
    _remove_sink_if_exists(sink_name)
    result = subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={sink_name}",
            f"sink_properties=device.description={sink_name}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create PulseAudio sink {sink_name}: {result.stderr.strip()}")
    monitor = f"{sink_name}.monitor"
    _ensure_source_exists(monitor)
    return monitor


def remove_session_sink(sink_name: str) -> None:
    _remove_sink_if_exists(sink_name)


def cleanup_stale_session_sinks(log=None) -> None:
    for module_id, sink_name in _loaded_null_sink_modules().items():
        if sink_name.startswith(SESSION_SINK_PREFIX):
            subprocess.run(["pactl", "unload-module", module_id], text=True, capture_output=True, check=False)
            if log:
                log.info("pulseaudio_stale_session_sink_removed", sink=sink_name, module_id=module_id)


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


def _ensure_source_exists(source_name: str) -> None:
    sources = subprocess.run(
        ["pactl", "list", "short", "sources"],
        text=True,
        capture_output=True,
        check=False,
    )
    if source_name in sources.stdout:
        return
    raise RuntimeError(f"PulseAudio source missing: {source_name}: {sources.stderr.strip() or sources.stdout.strip()}")


def _remove_sink_if_exists(sink_name: str) -> None:
    module_id = _loaded_null_sink_modules().get(sink_name)
    if module_id:
        subprocess.run(["pactl", "unload-module", module_id], text=True, capture_output=True, check=False)


def _loaded_null_sink_modules() -> dict[str, str]:
    result = subprocess.run(
        ["pactl", "list", "short", "modules"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return {}
    modules: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or parts[1] != "module-null-sink":
            continue
        match = re.search(r"\bsink_name=([A-Za-z0-9_]+)\b", parts[2])
        if match:
            modules[match.group(1)] = parts[0]
    return modules
