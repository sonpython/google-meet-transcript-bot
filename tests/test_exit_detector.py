import pytest

from src.bot.exit_detector import ExitDetector


class FakeLocator:
    def __init__(self, count: int = 0) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class FakePage:
    def __init__(self, url: str) -> None:
        self.url = url

    def is_closed(self) -> bool:
        return False

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator()


@pytest.mark.anyio
async def test_meet_homepage_counts_as_ended() -> None:
    reason = await ExitDetector().check_exit_signal(FakePage("https://meet.google.com/landing?authuser=0"), 2)

    assert reason == "ended"


@pytest.mark.anyio
async def test_meet_code_url_counts_as_active() -> None:
    reason = await ExitDetector().check_exit_signal(FakePage("https://meet.google.com/cvk-zmmx-wmr"), 2)

    assert reason is None

