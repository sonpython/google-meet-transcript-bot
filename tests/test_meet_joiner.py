import pytest

from src.bot.meet_joiner import MeetJoiner, _clean_meeting_title
from src.bot.meet_popups import dismiss_meet_popups


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
    def __init__(self, page, counts_for_join: bool = False) -> None:
        self.page = page
        self.counts_for_join = counts_for_join

    async def count(self) -> int:
        if not self.counts_for_join:
            return 0
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
        return FakeLocator(self, counts_for_join="Join now" in selector)


class PopupLocator:
    def __init__(self, button: FakeButton | None = None) -> None:
        self.button = button

    async def count(self) -> int:
        return 1 if self.button else 0

    def nth(self, index: int) -> FakeButton:
        return self.button


class PopupPage:
    def __init__(self) -> None:
        self.dismiss_button = FakeButton()

    def locator(self, selector: str) -> PopupLocator:
        if "Not now" in selector:
            return PopupLocator(self.dismiss_button)
        return PopupLocator()


class SignedOutPage:
    url = "https://accounts.google.com/v3/signin/accountchooser"

    async def goto(self, url: str, wait_until: str = "domcontentloaded"):
        return None


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


@pytest.mark.anyio
async def test_join_reports_signed_out_account() -> None:
    result = await MeetJoiner().join(SignedOutPage(), "abc-defg-hij", "Bot")

    assert result.status == "signed_out"
    assert result.error_msg == "bot Google session signed out; re-auth required"


@pytest.mark.anyio
async def test_dismiss_meet_popups_clicks_not_now_prompt() -> None:
    page = PopupPage()

    clicked = await dismiss_meet_popups(page)

    assert clicked == 1
    assert page.dismiss_button.clicked is True


def test_clean_meeting_title_removes_google_meet_suffix_and_rejects_fallback() -> None:
    assert _clean_meeting_title("Product Review - Google Meet", "Manual Meet abc-defg-hij") == "Product Review"
    assert _clean_meeting_title("Manual Meet abc-defg-hij", "Manual Meet abc-defg-hij") == ""
