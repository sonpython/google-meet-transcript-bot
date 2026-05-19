import asyncio

from src.bot.login_flow import LoginFlow
from src.bot.storage_state_store import StorageStateStore
from src.config import load_settings


async def main() -> None:
    settings = load_settings()
    store = StorageStateStore(settings.storage_state_path, settings.storage_passphrase)
    await LoginFlow(store).first_login()


if __name__ == "__main__":
    asyncio.run(main())
