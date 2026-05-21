import structlog

from src.bot.browser_session import BrowserSessionFactory
from src.bot.storage_state_store import StorageStateStore


class BotSessionKeepAlive:
    def __init__(
        self,
        browser_factory: BrowserSessionFactory,
        storage_state_store: StorageStateStore,
        url: str = "https://myaccount.google.com/",
    ) -> None:
        self.browser_factory = browser_factory
        self.storage_state_store = storage_state_store
        self.url = url
        self.log = structlog.get_logger(__name__)

    async def run(self) -> bool:
        session = await self.browser_factory.launch_with_state()
        try:
            await session.page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
            if self._is_signed_out(session.page.url):
                self.log.warning("bot_session_keepalive_signed_out", url=session.page.url)
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
