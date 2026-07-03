import time

import structlog

from src.bot.browser_session import BrowserSessionFactory
from src.bot.storage_state_store import StorageStateStore

ALERT_COOLDOWN_SECONDS = 6 * 3600


class BotSessionKeepAlive:
    """Keeps the bot's Google session warm by reopening its persistent Chromium
    profile on a short interval, exactly like a real user leaving Chrome open.

    Each cycle: open the on-disk profile headless, load a signed-in Google page
    so cookies/tokens rotate naturally on disk, then export a fresh storageState
    snapshot to the encrypted store the meeting flow reads from. No password is
    ever typed -- repeated headless password logins from a datacenter IP are what
    poison the account, so a real signed-out profile alerts a human to re-run the
    one-time login instead of attempting auto reauth.
    """

    def __init__(
        self,
        browser_factory: BrowserSessionFactory,
        storage_state_store: StorageStateStore,
        bot_email: str,
        url: str = "https://myaccount.google.com/",
        notifier=None,
    ) -> None:
        self.browser_factory = browser_factory
        self.storage_state_store = storage_state_store
        self.bot_email = bot_email
        self.url = url
        self.notifier = notifier
        self.log = structlog.get_logger(__name__)
        self._consecutive_failures = 0
        self._last_alert_monotonic: float | None = None

    async def run(self) -> bool:
        session = await self.browser_factory.launch_persistent()
        try:
            await session.page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
            if await self._is_signed_out(session.page):
                self.log.warning("bot_session_keepalive_signed_out", url=session.page.url)
                return await self._record_failure()
            # Export a fresh snapshot so ephemeral meeting contexts get rotated
            # cookies without contending for the persistent profile lock.
            self.storage_state_store.save(await session.context.storage_state())
            self.log.info("bot_session_keepalive_ok", url=session.page.url)
            await self._record_recovery()
            return True
        except Exception as exc:
            self.log.warning("bot_session_keepalive_failed", error=str(exc))
            return False
        finally:
            await session.close()

    async def _record_failure(self) -> bool:
        self._consecutive_failures += 1
        now = time.monotonic()
        cooldown_active = (
            self._last_alert_monotonic is not None
            and now - self._last_alert_monotonic < ALERT_COOLDOWN_SECONDS
        )
        if self.notifier and not cooldown_active:
            self._last_alert_monotonic = now
            await self._notify(
                "ALERT: bot Google session signed out: re-run the one-time persistent login"
            )
        return False

    async def _record_recovery(self) -> None:
        if self._consecutive_failures and self.notifier:
            await self._notify("OK: bot Google session restored")
        self._consecutive_failures = 0
        self._last_alert_monotonic = None

    async def _notify(self, text: str) -> None:
        try:
            await self.notifier.send_text(text)
        except Exception as exc:
            self.log.warning("bot_session_keepalive_notify_failed", error=str(exc))

    async def _is_signed_out(self, page) -> bool:
        url = getattr(page, "url", "")
        if "accounts.google.com" in url:
            return True
        if "myaccount.google.com" not in url:
            return True
        try:
            body = await page.locator("body").inner_text(timeout=1_000)
        except Exception:
            return False
        normalized = " ".join(body.lower().split())
        return "sign in" in normalized or "đăng nhập" in normalized
