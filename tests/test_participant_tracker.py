import pytest

from src.bot import meet_selectors as sel
from src.bot.participant_tracker import ParticipantTracker


class FakeButton:
    def __init__(self, *, visible: bool, enabled: bool) -> None:
        self.visible = visible
        self.enabled = enabled
        self.clicked = False

    async def is_visible(self) -> bool:
        return self.visible

    async def is_enabled(self) -> bool:
        return self.enabled

    async def click(self, timeout: int = 0) -> None:
        self.clicked = True


class FakeLocator:
    def __init__(self, items=None, texts=None) -> None:
        self.items = items or []
        self.texts = texts or []

    async def count(self) -> int:
        return len(self.items)

    def nth(self, index: int):
        return self.items[index]

    async def all_text_contents(self) -> list[str]:
        return self.texts


class FakePage:
    def __init__(self, buttons: list[FakeButton], names: list[str]) -> None:
        self.buttons = buttons
        self.names = names

    def locator(self, selector: str) -> FakeLocator:
        if selector == sel.PARTICIPANT_NAMES:
            return FakeLocator(texts=self.names)
        if selector == sel.PARTICIPANT_LIST_BTNS[0]:
            return FakeLocator(items=self.buttons)
        return FakeLocator()


@pytest.mark.anyio
async def test_participant_tracker_skips_hidden_disabled_buttons() -> None:
    hidden = FakeButton(visible=False, enabled=False)
    visible = FakeButton(visible=True, enabled=True)
    page = FakePage([hidden, visible], [" Bot ", "An", "An"])

    names = await ParticipantTracker().get_participants(page)

    assert not hidden.clicked
    assert visible.clicked
    assert names == ["Bot", "An"]


@pytest.mark.anyio
async def test_participant_tracker_does_not_fail_when_panel_button_is_unavailable() -> None:
    page = FakePage([FakeButton(visible=False, enabled=False)], ["Bot"])

    names = await ParticipantTracker().get_participants(page)

    assert names == ["Bot"]
