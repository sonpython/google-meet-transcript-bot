import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RuntimeStatus:
    def __init__(self, path: Path = Path("/tmp/meeting-assistant-status.json")) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "service": "meeting-assistant",
            "state": "starting",
            "detail": "",
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def set(self, state: str, detail: str = "", **extra: Any) -> None:
        with self._lock:
            self._state.update(
                {
                    "state": state,
                    "detail": detail,
                    "updated_at": datetime.now(UTC).isoformat(),
                    **extra,
                }
            )
            self.path.write_text(json.dumps(self._state, ensure_ascii=False))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)


STATUS = RuntimeStatus()
