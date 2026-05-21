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


class BotSessionKeepAlive:
    def __init__(
        self,
        browser_factory: BrowserSessionFactory,
        storage_state_store: StorageStateStore,
        bot_email: str,
        bot_password: str | None = None,
        url: str = "https://myaccount.google.com/",
    ) -> None:
        self.browser_factory = browser_factory
        self.storage_state_store = storage_state_store
        self.bot_email = bot_email
        self.bot_password = bot_password
        self.url = url
        self.log = structlog.get_logger(__name__)

    async def run(self) -> bool:
        session = await self.browser_factory.launch_with_state()
        try:
            await session.page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
            if self._is_signed_out(session.page.url):
                self.log.warning("bot_session_keepalive_signed_out", url=session.page.url)
                if not await self._reauth(session.page):
                    return False
            self.storage_state_store.save(await session.context.storage_state())
            self.log.info("bot_session_keepalive_ok", url=session.page.url)
            return True
        except Exception as exc:
            self.log.warning("bot_session_keepalive_failed", error=str(exc))
            return False
        finally:
            await session.close()

    def _is_signed_out(self, url: str) -> bool:
        return "accounts.google.com" in url

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
