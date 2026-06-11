"""Headed bot re-login that auto-saves encrypted storageState once Google login completes.

Usage:
    STORAGE_PASSPHRASE=... uv run python scripts/bot_reauth_local.py --out /tmp/storage-state.fernet

Opens a visible Chromium window; log in as the bot account. The script detects
arrival at myaccount.google.com and saves the encrypted storage state, no
manual Enter needed (unlike bot_first_login_manual.py).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from src.bot.storage_state_store import StorageStateStore

LOGIN_URL = (
    "https://accounts.google.com/ServiceLogin"
    "?service=accountsettings&continue=https%3A%2F%2Fmyaccount.google.com%2F"
)


async def _run(out_path: Path, passphrase: str, timeout_minutes: int) -> int:
    store = StorageStateStore(out_path, passphrase)
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()
    try:
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("Log in as the bot account in the opened browser window...", flush=True)
        # Match on the URL host only: the accounts.google.com login URL carries
        # myaccount.google.com inside its continue= param, so a substring glob
        # would fire before login completes.
        await page.wait_for_url(
            lambda url: urlparse(url).hostname == "myaccount.google.com",
            timeout=timeout_minutes * 60_000,
        )
        # Give Google a moment to settle post-login cookies before snapshotting.
        await page.wait_for_timeout(3_000)
        state = await context.storage_state()
        cookie_names = {cookie.get("name", "") for cookie in state.get("cookies", [])}
        if "SID" not in cookie_names:
            print(f"Login looks incomplete (no SID cookie; got {sorted(cookie_names)})", file=sys.stderr)
            return 1
        store.save(state)
        print(f"Saved encrypted storage state to {out_path}", flush=True)
        return 0
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Output path for encrypted storage state")
    parser.add_argument("--timeout-minutes", type=int, default=10)
    args = parser.parse_args()
    passphrase = os.environ.get("STORAGE_PASSPHRASE", "")
    if not passphrase:
        print("STORAGE_PASSPHRASE env var is required", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(_run(Path(args.out), passphrase, args.timeout_minutes)))


if __name__ == "__main__":
    main()
