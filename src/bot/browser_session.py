from dataclasses import dataclass

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from src.bot.storage_state_store import StorageStateStore


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


class BrowserSessionFactory:
    def __init__(self, state_store: StorageStateStore, headless: bool = True) -> None:
        self.state_store = state_store
        self.headless = headless

    async def launch_with_state(self) -> BrowserSession:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--use-fake-ui-for-media-stream"],
        )
        state = self.state_store.load()
        context = await browser.new_context(
            storage_state=state,
            viewport={"width": 1366, "height": 768},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            color_scheme="light",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await context.new_page()
        return BrowserSession(playwright, browser, context, page)
