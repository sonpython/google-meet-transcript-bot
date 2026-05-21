import pytest

from src.bot.meet_joiner import MeetJoiner


class FakeButton:
    def __init__(self) -> None:
        self.clicked = False

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def click(self, timeout: int = 1000) -> None:
        self.clicked = True


class FakeLocator:
    def __init__(self, page) -> None:
        self.page = page

    async def count(self) -> int:
        self.page.polls += 1
        return 1 if self.page.polls >= self.page.visible_after else 0

    def nth(self, index: int) -> FakeButton:
        return self.page.button


class FakePage:
    def __init__(self, visible_after: int) -> None:
        self.visible_after = visible_after
        self.polls = 0
        self.button = FakeButton()

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self)


@pytest.mark.anyio
async def test_wait_and_click_join_button_retries_until_button_renders() -> None:
    page = FakePage(visible_after=3)

    clicked = await MeetJoiner()._wait_and_click_join_button(
        page,
        ["button:has-text('Join now')"],
        timeout=5,
        poll_seconds=0,
    )

    assert clicked is True
    assert page.button.clicked is True
    assert page.polls == 3

