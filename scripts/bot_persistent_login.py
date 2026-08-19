"""One-time headed login that populates the persistent Chromium profile.

Usage:
    STORAGE_PASSPHRASE=... uv run python scripts/bot_persistent_login.py \
        --user-data-dir /data/bot-profile \
        --out /data/tokens/storage-state.fernet \
        --expected-email bot@example.com

Opens a visible Chromium window backed by the on-disk profile at --user-data-dir.
Log in as the bot account once; everything (cookies, localStorage, IndexedDB,
device id) is written into that profile dir, which the keepalive then reopens
headless to keep warm -- no password is ever typed again. The script also exports
an encrypted storageState snapshot to --out so the meeting flow's ephemeral
contexts have signed-in cookies immediately, before the first keepalive cycle.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from src.bot.storage_state_store import StorageStateStore

LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=accountsettings&continue=https%3A%2F%2Fmyaccount.google.com%2F"
EMAIL_URL = "https://myaccount.google.com/email"


async def _run(
    user_data_dir: Path,
    out_path: Path,
    passphrase: str,
    timeout_minutes: int,
    expected_email: str | None,
    auto_password: str | None,
) -> int:
    store = StorageStateStore(out_path, passphrase)
    user_data_dir.mkdir(parents=True, exist_ok=True)
    playwright = await async_playwright().start()
    context = await playwright.chromium.launch_persistent_context(
        str(user_data_dir),
        headless=False,
    )
    page = context.pages[0] if context.pages else await context.new_page()
    try:
        await page.goto(_login_url(expected_email), wait_until="domcontentloaded")
        print("Log in as the bot account in the opened browser window...", flush=True)
        if expected_email and auto_password:
            await _try_auto_login(page, expected_email, auto_password)
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
        if expected_email and not await _verify_expected_email(page, expected_email):
            print(
                f"Logged-in Google account is not {expected_email}; refusing to save state.",
                file=sys.stderr,
            )
            return 1
        store.save(state)
        print(f"Persistent profile ready at {user_data_dir}", flush=True)
        print(f"Saved encrypted storage state snapshot to {out_path}", flush=True)
        return 0
    finally:
        await context.close()
        await playwright.stop()


async def _verify_expected_email(page, expected_email: str) -> bool:
    await page.goto(EMAIL_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2_000)
    try:
        body = await page.locator("body").inner_text(timeout=5_000)
    except Exception:
        return False
    return expected_email.lower() in " ".join(body.lower().split())


async def _try_auto_login(page, email: str, password: str) -> None:
    try:
        email_input = page.locator('input[type="email"], #identifierId').first
        if await email_input.count():
            # Google's confirmidentifier page pre-fills the identifier in a
            # hidden input; filling it hangs. Only type when the field is
            # actually visible, otherwise just confirm with Next.
            if await email_input.is_visible():
                await email_input.fill(email)
            await _click_next(page)
        password_input = page.locator('input[type="password"]').first
        await password_input.wait_for(state="visible", timeout=20_000)
        await password_input.fill(password)
        await _click_next(page)
    except Exception as exc:
        print(f"Auto-fill did not complete; continue manually in the browser ({exc})", flush=True)


async def _click_next(page) -> None:
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


def _login_url(expected_email: str | None) -> str:
    if not expected_email:
        return LOGIN_URL
    return f"{LOGIN_URL}&prompt=select_account&login_hint={quote(expected_email)}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-data-dir",
        default=os.environ.get("BOT_USER_DATA_DIR", "/data/bot-profile"),
        help="On-disk Chromium profile dir to populate (kept warm by the keepalive)",
    )
    parser.add_argument(
        "--out",
        default=os.environ.get("STORAGE_STATE_PATH", "/data/tokens/storage-state.fernet"),
        help="Output path for the encrypted storageState snapshot used by meetings",
    )
    parser.add_argument("--timeout-minutes", type=int, default=10)
    parser.add_argument(
        "--expected-email",
        default=os.environ.get("BOT_EMAIL"),
        help="Refuse to save state unless the logged-in Google account matches this email",
    )
    parser.add_argument(
        "--auto-password",
        action="store_true",
        help="Use BOT_PASSWORD to fill the Google password step, then wait for any manual verification",
    )
    args = parser.parse_args()
    passphrase = os.environ.get("STORAGE_PASSPHRASE", "")
    if not passphrase:
        print("STORAGE_PASSPHRASE env var is required", file=sys.stderr)
        sys.exit(2)
    auto_password = os.environ.get("BOT_PASSWORD") if args.auto_password else None
    sys.exit(
        asyncio.run(
            _run(
                Path(args.user_data_dir),
                Path(args.out),
                passphrase,
                args.timeout_minutes,
                args.expected_email,
                auto_password,
            )
        )
    )


if __name__ == "__main__":
    main()
