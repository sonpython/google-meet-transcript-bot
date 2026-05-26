import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import structlog

Sleep = Callable[[float], Awaitable[None]]


class PeriodicScreenshotCapturer:
    def __init__(
        self,
        page,
        screenshot_dir: Path,
        meet_code: str,
        interval_seconds: int = 5 * 60,
        clock: Callable[[], datetime] | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        self.page = page
        self.screenshot_dir = screenshot_dir
        self.meet_code = meet_code
        self.interval_seconds = max(1, interval_seconds)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleep = sleep or asyncio.sleep
        self.log = structlog.get_logger(__name__)
        self._task: asyncio.Task | None = None
        self.paths: list[Path] = []

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def capture_once(self) -> Path | None:
        path = self._next_path()
        try:
            await self.page.screenshot(path=str(path), full_page=False)
        except Exception as exc:
            self.log.warning(
                "meeting_screenshot_capture_failed",
                meet_code=self.meet_code,
                error=str(exc),
            )
            return None
        self.paths.append(path)
        self.log.info("meeting_screenshot_captured", meet_code=self.meet_code, path=str(path))
        return path

    async def _run(self) -> None:
        while True:
            await self.capture_once()
            await self.sleep(self.interval_seconds)

    def _next_path(self) -> Path:
        stamp = self.clock().strftime("%Y%m%dT%H%M%SZ")
        directory = self.screenshot_dir / self.meet_code
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.meet_code}-{stamp}.png"
        if not path.exists():
            return path
        index = 2
        while True:
            indexed_path = directory / f"{self.meet_code}-{stamp}-{index}.png"
            if not indexed_path.exists():
                return indexed_path
            index += 1
