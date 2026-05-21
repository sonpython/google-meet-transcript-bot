import asyncio
from datetime import UTC, datetime

from src.bot import meet_selectors as sel
from src.bot.join_result import JoinResult


class MeetJoiner:
    async def join(self, page, meet_code: str, display_name: str, timeout: int = 300) -> JoinResult:
        try:
            await page.goto(f"https://meet.google.com/{meet_code}", wait_until="domcontentloaded")
            signed_out = await self._signed_out(page)
            if signed_out:
                return JoinResult("signed_out", error_msg="bot Google session signed out; re-auth required")
            await self._fill_name_if_needed(page, display_name)
            await self._ensure_media_off(page)
            clicked = await self._wait_and_click_join_button(
                page,
                [sel.JOIN_HERE_TOO_BTN, sel.JOIN_NOW_BTN, sel.ASK_TO_JOIN_BTN, sel.SWITCH_HERE_BTN],
                timeout=min(90, timeout),
            )
            if not clicked:
                return JoinResult("timeout", error_msg="join button not found")
            return await self._wait_for_outcome(page, timeout)
        except Exception as exc:
            return JoinResult("network_error", error_msg=str(exc))

    async def _signed_out(self, page) -> bool:
        if "accounts.google.com" in getattr(page, "url", ""):
            return True
        try:
            body = await page.locator("body").inner_text(timeout=1000)
        except Exception:
            return False
        normalized = " ".join(body.lower().split())
        return "đã đăng xuất" in normalized or "signed out" in normalized

    async def _fill_name_if_needed(self, page, display_name: str) -> None:
        locator = page.locator(sel.NAME_INPUT)
        if await locator.count():
            await locator.first.fill(display_name)

    async def _ensure_media_off(self, page) -> None:
        for selector in (sel.MIC_TOGGLE, sel.CAM_TOGGLE):
            locator = page.locator(selector)
            if await locator.count():
                pressed = await locator.first.get_attribute("aria-pressed")
                if pressed == "true":
                    await locator.first.click()

    async def _click_first_visible(self, page, selectors: list[str]) -> bool:
        for selector in selectors:
            locator = page.locator(selector)
            for index in range(await locator.count()):
                button = locator.nth(index)
                try:
                    if not await button.is_visible() or not await button.is_enabled():
                        continue
                    await button.click(timeout=1000)
                    return True
                except Exception:
                    continue
        return False

    async def _wait_and_click_join_button(
        self,
        page,
        selectors: list[str],
        timeout: int,
        poll_seconds: float = 1,
    ) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if await self._click_first_visible(page, selectors):
                return True
            await asyncio.sleep(poll_seconds)
        return False

    async def _wait_for_outcome(self, page, timeout: int) -> JoinResult:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if await self._click_visible(page, sel.CONSENT_JOIN_NOW_BTN):
                await asyncio.sleep(1)
                continue
            if await self._click_visible(page, sel.GOT_IT_BTN):
                await asyncio.sleep(1)
                continue
            if await page.locator(sel.LEAVE_BTN).count():
                return JoinResult("admitted", joined_at=datetime.now(UTC))
            if await page.locator(sel.RISK_QUEUE_TEXT).count():
                return JoinResult("risk_queue_denied", error_msg="risk queue denial detected")
            if await page.locator(sel.DENIED_TEXT).count():
                return JoinResult("denied", error_msg="host denied or did not respond")
            await asyncio.sleep(2)
        return JoinResult("timeout", error_msg="join wait timed out")

    async def _click_visible(self, page, selector: str) -> bool:
        locator = page.locator(selector)
        for index in range(await locator.count()):
            button = locator.nth(index)
            try:
                if await button.is_visible() and await button.is_enabled():
                    await button.click(timeout=1000)
                    return True
            except Exception:
                continue
        return False
