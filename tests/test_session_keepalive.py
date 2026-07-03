import pytest

from src.bot.session_keepalive import BotSessionKeepAlive


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_text(self, text: str) -> None:
        self.messages.append(text)


class FakePage:
    def __init__(self, final_url: str) -> None:
        self.url = final_url
        self.visited_url = None

    async def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.visited_url = url

    def locator(self, selector: str):
        raise RuntimeError("no DOM in fake page")


class FakeContext:
    async def storage_state(self) -> dict:
        return {"cookies": [{"name": "session"}], "origins": []}


class FakeSession:
    def __init__(self, final_url: str) -> None:
        self.page = FakePage(final_url)
        self.context = FakeContext()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBrowserFactory:
    def __init__(self, final_url: str) -> None:
        self.session = FakeSession(final_url)
        self.launched_persistent = False

    async def launch_persistent(self):
        self.launched_persistent = True
        return self.session


class FakeStorageStore:
    def __init__(self) -> None:
        self.saved = None

    def save(self, state: dict) -> None:
        self.saved = state


@pytest.mark.anyio
async def test_keepalive_saves_refreshed_state_from_persistent_profile() -> None:
    factory = FakeBrowserFactory("https://myaccount.google.com/")
    store = FakeStorageStore()

    ok = await BotSessionKeepAlive(factory, store, "bot@example.com").run()

    assert ok is True
    assert factory.launched_persistent is True
    assert factory.session.page.visited_url == "https://myaccount.google.com/"
    assert store.saved == {"cookies": [{"name": "session"}], "origins": []}
    assert factory.session.closed is True


@pytest.mark.anyio
async def test_keepalive_does_not_save_when_signed_out() -> None:
    factory = FakeBrowserFactory("https://accounts.google.com/v3/signin/accountchooser")
    store = FakeStorageStore()

    ok = await BotSessionKeepAlive(factory, store, "bot@example.com").run()

    assert ok is False
    assert store.saved is None
    assert factory.session.closed is True


@pytest.mark.anyio
async def test_keepalive_treats_public_account_page_as_signed_out() -> None:
    factory = FakeBrowserFactory("https://www.google.com/account/about/?hl=vi")
    store = FakeStorageStore()

    ok = await BotSessionKeepAlive(factory, store, "bot@example.com").run()

    assert ok is False
    assert store.saved is None
    assert factory.session.closed is True


@pytest.mark.anyio
async def test_keepalive_alerts_once_within_cooldown_when_signed_out() -> None:
    factory = FakeBrowserFactory("https://accounts.google.com/v3/signin/accountchooser")
    notifier = FakeNotifier()
    keepalive = BotSessionKeepAlive(factory, FakeStorageStore(), "bot@example.com", notifier=notifier)

    assert await keepalive.run() is False
    assert await keepalive.run() is False

    assert notifier.messages == [
        "ALERT: bot Google session signed out: re-run the one-time persistent login"
    ]


@pytest.mark.anyio
async def test_keepalive_sends_recovery_message_after_failures() -> None:
    factory = FakeBrowserFactory("https://accounts.google.com/v3/signin/accountchooser")
    notifier = FakeNotifier()
    keepalive = BotSessionKeepAlive(factory, FakeStorageStore(), "bot@example.com", notifier=notifier)
    assert await keepalive.run() is False

    factory.session.page.url = "https://myaccount.google.com/"
    assert await keepalive.run() is True

    assert notifier.messages[-1] == "OK: bot Google session restored"
    assert keepalive._consecutive_failures == 0
