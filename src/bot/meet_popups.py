AI_PROMPT_TEXT = (
    "AI",
    "Gemini",
    "Take notes",
    "Help me write",
    "Studio",
    "Duet",
)

DISMISS_BUTTON_SELECTORS = (
    'button:has-text("Not now")',
    'button:has-text("No thanks")',
    'button:has-text("Dismiss")',
    'button:has-text("Close")',
    'button:has-text("Got it")',
    'button:has-text("Skip")',
    'button:has-text("Maybe later")',
    'button:has-text("Không phải bây giờ")',
    'button:has-text("Không, cảm ơn")',
    'button:has-text("Đóng")',
    'button:has-text("Đã hiểu")',
)


async def dismiss_meet_popups(page) -> int:
    clicked = 0
    for selector in DISMISS_BUTTON_SELECTORS:
        clicked += await _click_visible(page, selector)
    clicked += await _dismiss_ai_dialog_buttons(page)
    return clicked


async def _dismiss_ai_dialog_buttons(page) -> int:
    count = 0
    for text in AI_PROMPT_TEXT:
        try:
            dialog = page.locator(f'[role="dialog"]:has-text("{text}")')
        except Exception:
            continue
        for index in range(await _safe_count(dialog)):
            node = dialog.nth(index)
            for selector in DISMISS_BUTTON_SELECTORS:
                try:
                    button = node.locator(selector)
                except Exception:
                    continue
                count += await _click_locator_buttons(button)
    return count


async def _click_visible(page, selector: str) -> int:
    try:
        locator = page.locator(selector)
    except Exception:
        return 0
    return await _click_locator_buttons(locator)


async def _click_locator_buttons(locator) -> int:
    clicked = 0
    for index in range(await _safe_count(locator)):
        button = locator.nth(index)
        try:
            if not await button.is_visible() or not await button.is_enabled():
                continue
            await button.click(timeout=500)
            clicked += 1
        except Exception:
            continue
    return clicked


async def _safe_count(locator) -> int:
    try:
        return await locator.count()
    except Exception:
        return 0
