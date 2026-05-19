from playwright.async_api import async_playwright

from src.bot.storage_state_store import StorageStateStore


class LoginFlow:
    def __init__(self, state_store: StorageStateStore) -> None:
        self.state_store = state_store

    async def first_login(self) -> None:
        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.launch(headless=False)
            context = await browser.new_context()
            try:
                page = await context.new_page()
                await page.goto("https://accounts.google.com")
                await page.wait_for_url("**/myaccount.google.com/**", timeout=0)
                self.state_store.save(await context.storage_state())
            finally:
                await context.close()
                await browser.close()
        finally:
            await playwright.stop()

    async def verify_session(self, page) -> bool:
        await page.goto("https://myaccount.google.com", wait_until="domcontentloaded")
        return "accounts.google.com" not in page.url
