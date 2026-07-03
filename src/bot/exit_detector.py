import re
from urllib.parse import urlparse

from src.bot import meet_selectors as sel

MEET_CODE_PATH = re.compile(r"^/[a-z]{3}-[a-z]{4}-[a-z]{3}(?:$|[/?#])", re.IGNORECASE)


class ExitDetector:
    async def check_exit_signal(self, page, participant_count: int | None = None) -> str | None:
        if getattr(page, "is_closed", lambda: False)():
            return "page_closed"
        if await page.locator(sel.REMOVED_DIALOG).count():
            return "kicked"
        if await page.locator(sel.MEETING_ENDED).count():
            return "ended"
        if not _is_active_meet_url(getattr(page, "url", "")):
            return "ended"
        if participant_count == 1:
            return "alone_signal"
        return None


def _is_active_meet_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.hostname != "meet.google.com":
        return False
    return bool(MEET_CODE_PATH.match(parsed.path))
