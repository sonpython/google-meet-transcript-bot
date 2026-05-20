from src.bot import meet_selectors as sel


class ParticipantTracker:
    async def get_participants(self, page) -> list[str]:
        await self._open_participants_panel(page)
        names: list[str] = []
        for raw in await page.locator(sel.PARTICIPANT_NAMES).all_text_contents():
            cleaned = raw.strip()
            if cleaned and cleaned not in names:
                names.append(cleaned)
        return names

    async def _open_participants_panel(self, page) -> None:
        for selector in sel.PARTICIPANT_LIST_BTNS:
            buttons = page.locator(selector)
            for index in range(await buttons.count()):
                button = buttons.nth(index)
                try:
                    if not await button.is_visible() or not await button.is_enabled():
                        continue
                    await button.click(timeout=1000)
                    return
                except Exception:
                    continue
