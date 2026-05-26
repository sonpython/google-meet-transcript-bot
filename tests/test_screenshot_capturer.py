import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from src.bot.screenshot_capturer import PeriodicScreenshotCapturer


class FakePage:
    def __init__(self) -> None:
        self.calls = []

    async def screenshot(self, **kwargs):
        path = kwargs["path"]
        self.calls.append(kwargs)
        with open(path, "wb") as file:
            file.write(b"png")


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 5, 20, tzinfo=UTC)

    def now(self) -> datetime:
        value = self.current
        self.current += timedelta(minutes=5)
        return value


@pytest.mark.anyio
async def test_capture_once_writes_viewport_screenshot_under_meeting_directory(tmp_path) -> None:
    page = FakePage()
    capturer = PeriodicScreenshotCapturer(
        page,
        tmp_path,
        "abc-defg-hij",
        clock=FakeClock().now,
    )

    path = await capturer.capture_once()

    assert path == tmp_path / "abc-defg-hij" / "abc-defg-hij-20260520T000000Z.png"
    assert path.read_bytes() == b"png"
    assert page.calls == [{"path": str(path), "full_page": False}]
    assert capturer.paths == [path]


@pytest.mark.anyio
async def test_start_captures_immediately_then_stops_cleanly(tmp_path) -> None:
    page = FakePage()
    sleep_started = asyncio.Event()

    async def sleep(seconds: float) -> None:
        assert seconds == 300
        sleep_started.set()
        await asyncio.Future()

    capturer = PeriodicScreenshotCapturer(
        page,
        tmp_path,
        "abc-defg-hij",
        interval_seconds=300,
        clock=FakeClock().now,
        sleep=sleep,
    )

    capturer.start()
    await asyncio.wait_for(sleep_started.wait(), timeout=1)
    await capturer.stop()

    assert len(page.calls) == 1
    assert capturer.paths[0].exists()
    assert capturer._task is None
