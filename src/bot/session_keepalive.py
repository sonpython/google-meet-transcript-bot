import time

import structlog
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.bot.browser_session import BrowserSessionFactory
from src.bot.storage_state_store import StorageStateStore

LOGIN_CHALLENGE_MARKERS = (
    "2-step verification",
    "verify it",
    "verify it’s you",
    "verify it's you",
    "captcha",
    "xác minh",
    "xác minh bạn",
)

# Repeated headless password logins from a datacenter IP look like an attack to
# Google and can poison the bot account's reputation, so reauth attempts pause
# after this many consecutive sign-in failures until a human restores the session.
MAX_CONSECUTIVE_REAUTH_FAILURES = 3
ALERT_COOLDOWN_SECONDS = 6 * 3600


class BotSessionKeepAlive:
    def __init__(
        self,
        browser_factory: BrowserSessionFactory,
        storage_state_store: StorageStateStore,
        bot_email: str,
        bot_password: str | None = None,
        url: str = "https://myaccount.google.com/",
        notifier=None,
    ) -> None:
        self.browser_factory = browser_factory
        self.storage_state_store = storage_state_store
        self.bot_email = bot_email
        self.bot_password = bot_password
        self.url = url
        self.notifier = notifier
        self.log = structlog.get_logger(__name__)
        self._consecutive_failures = 0
        self._last_alert_monotonic: float | None = None

    async def run(self) -> bool:
        session = await self.browser_factory.launch_with_state()
        try:
            await session.page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
            if await self._is_signed_out(session.page):
                self.log.warning("bot_session_keepalive_signed_out", url=session.page.url)
                if self._consecutive_failures >= MAX_CONSECUTIVE_REAUTH_FAILURES:
                    self.log.warning(
                        "bot_session_reauth_paused",
                        consecutive_failures=self._consecutive_failures,
                    )
                elif not await self._reauth(session.page):
                    return await self._record_failure()
            if await self._is_signed_out(session.page):
                self.log.warning("bot_session_keepalive_still_signed_out", url=session.page.url)
                return await self._record_failure()
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
                "ALERT: bot Google session signed out and auto reauth failed: manual relogin required"
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

    async def _reauth(self, page) -> bool:
        if not self.bot_password:
            self.log.warning("bot_session_reauth_skipped", reason="missing_bot_password")
            return False
        try:
            await self._choose_or_enter_email(page)
            await self._enter_password(page)
            await page.wait_for_url("**/myaccount.google.com/**", timeout=30_000)
            self.log.info("bot_session_reauth_ok")
            return True
        except Exception as exc:
            if await self._has_login_challenge(page):
                self.log.warning("bot_session_reauth_needs_manual_verification", url=getattr(page, "url", ""))
            else:
                self.log.warning("bot_session_reauth_failed", error=str(exc), url=getattr(page, "url", ""))
            return False

    async def _choose_or_enter_email(self, page) -> None:
        email_input = page.locator('input[type="email"], #identifierId').first
        if await email_input.count():
            await email_input.fill(self.bot_email)
            await self._click_next(page)
            return
        account_tile = page.get_by_text(self.bot_email, exact=False)
        if await account_tile.count():
            await account_tile.first.click()
            return
        await page.goto(
            "https://accounts.google.com/ServiceLogin"
            "?service=accountsettings&continue=https%3A%2F%2Fmyaccount.google.com%2F",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        account_tile = page.get_by_text(self.bot_email, exact=False)
        if await account_tile.count():
            await account_tile.first.click()
            return
        email_input = page.locator('input[type="email"], #identifierId').first
        await email_input.wait_for(state="visible", timeout=20_000)
        await email_input.fill(self.bot_email)
        await self._click_next(page)

    async def _enter_password(self, page) -> None:
        password_input = page.locator('input[type="password"]').first
        await password_input.wait_for(state="visible", timeout=20_000)
        await password_input.fill(self.bot_password or "")
        await self._click_next(page)

    async def _click_next(self, page) -> None:
        buttons = (
            page.get_by_role("button", name="Next"),
            page.get_by_role("button", name="Tiếp theo"),
            page.locator("#identifierNext button, #passwordNext button").first,
        )
        for button in buttons:
            try:
                if await button.count():
                    await button.first.click(timeout=5_000)
                    return
            except PlaywrightTimeoutError:
                continue
        raise RuntimeError("Google login next button not found")

    async def _has_login_challenge(self, page) -> bool:
        try:
            body = await page.locator("body").inner_text(timeout=1_000)
        except Exception:
            return False
        normalized = " ".join(body.lower().split())
        return any(marker in normalized for marker in LOGIN_CHALLENGE_MARKERS)
