from src.bot import meet_selectors as sel


class ExitDetector:
    async def check_exit_signal(self, page, participant_count: int | None = None) -> str | None:
        if getattr(page, "is_closed", lambda: False)():
            return "page_closed"
        if await page.locator(sel.REMOVED_DIALOG).count():
            return "kicked"
        if await page.locator(sel.MEETING_ENDED).count():
            return "ended"
        if "meet.google.com" not in getattr(page, "url", ""):
            return "ended"
        if participant_count == 1:
            return "alone_signal"
        return None
