from src.bot import meet_selectors as sel


class ParticipantTracker:
    async def get_participants(self, page) -> list[str]:
        button = page.locator(sel.PARTICIPANT_LIST_BTN)
        if await button.count():
            await button.first.click()
        names: list[str] = []
        for raw in await page.locator(sel.PARTICIPANT_NAMES).all_text_contents():
            cleaned = raw.strip()
            if cleaned and cleaned not in names:
                names.append(cleaned)
        return names
