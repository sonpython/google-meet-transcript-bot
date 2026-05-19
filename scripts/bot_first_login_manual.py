import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from src.bot.storage_state_store import StorageStateStore


async def _run(storage_state_path: Path, storage_passphrase: str) -> None:
    store = StorageStateStore(storage_state_path, storage_passphrase)
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("https://accounts.google.com", wait_until="domcontentloaded")
    print("Login the bot account in the opened browser, then press Enter here to save state.", flush=True)
    input()
    store.save(await context.storage_state())
    await context.close()
    await browser.close()
    await playwright.stop()
    print(f"Saved encrypted storage state to {storage_state_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual bot login and encrypted Playwright storageState save.")
    parser.add_argument("--storage-state-path", required=True)
    parser.add_argument("--storage-passphrase", required=True)
    args = parser.parse_args()
    asyncio.run(_run(Path(args.storage_state_path), args.storage_passphrase))


if __name__ == "__main__":
    main()
