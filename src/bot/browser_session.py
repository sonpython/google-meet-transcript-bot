from dataclasses import dataclass
import os
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from src.bot.storage_state_store import StorageStateStore

# Shared hardening + fingerprint so the persistent profile and the ephemeral
# meeting contexts present an identical, human-looking browser to Google.
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-crash-reporter",
    "--disable-crashpad",
    "--disable-dev-shm-usage",
    "--use-fake-ui-for-media-stream",
]
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_CONTEXT_OPTS = {
    "viewport": {"width": 1366, "height": 768},
    "locale": "vi-VN",
    "timezone_id": "Asia/Ho_Chi_Minh",
    "color_scheme": "light",
    "user_agent": _USER_AGENT,
}
_WEBDRIVER_PATCH = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


@dataclass
class BrowserSession:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page

    async def close(self) -> None:
        try:
            await self.context.close()
        finally:
            try:
                await self.browser.close()
            finally:
                await self.playwright.stop()


@dataclass
class PersistentBrowserSession:
    """A persistent-profile session: launch_persistent_context owns the browser,
    so there is no separate Browser handle to close."""

    playwright: Playwright
    context: BrowserContext
    page: Page

    async def close(self) -> None:
        try:
            await self.context.close()
        finally:
            await self.playwright.stop()


class BrowserSessionFactory:
    def __init__(
        self,
        state_store: StorageStateStore,
        headless: bool = True,
        user_data_dir: Path | str | None = None,
    ) -> None:
        self.state_store = state_store
        self.headless = headless
        self.user_data_dir = Path(user_data_dir) if user_data_dir else None

    async def launch_with_state(self, pulse_sink: str | None = None) -> BrowserSession:
        playwright = await async_playwright().start()
        env = os.environ.copy()
        if pulse_sink:
            env["PULSE_SINK"] = pulse_sink
        browser = await playwright.chromium.launch(
            headless=self.headless,
            args=_LAUNCH_ARGS,
            env=env,
        )
        state = self.state_store.load()
        context = await browser.new_context(storage_state=state, **_CONTEXT_OPTS)
        await context.add_init_script(_WEBDRIVER_PATCH)
        page = await context.new_page()
        return BrowserSession(playwright, browser, context, page)

    async def launch_persistent(self, pulse_sink: str | None = None) -> PersistentBrowserSession:
        """Open the on-disk Chromium profile. Only one process may hold the
        profile lock at a time, so this backs the keepalive; the meeting flow
        uses launch_with_state() ephemeral contexts off the exported snapshot."""
        if not self.user_data_dir:
            raise RuntimeError("user_data_dir is not configured for persistent profile")
        playwright = await async_playwright().start()
        env = os.environ.copy()
        if pulse_sink:
            env["PULSE_SINK"] = pulse_sink
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        context = await playwright.chromium.launch_persistent_context(
            str(self.user_data_dir),
            headless=self.headless,
            args=_LAUNCH_ARGS,
            env=env,
            **_CONTEXT_OPTS,
        )
        await context.add_init_script(_WEBDRIVER_PATCH)
        page = context.pages[0] if context.pages else await context.new_page()
        return PersistentBrowserSession(playwright, context, page)
