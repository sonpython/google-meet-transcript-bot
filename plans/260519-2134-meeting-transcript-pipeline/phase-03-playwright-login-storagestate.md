---
phase: 3
title: "Playwright Login + storageState"
status: implemented
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 3: Playwright Login + storageState

## Overview

Login `bot@your-domain.com` qua Playwright, persist session cookies vào encrypted `storageState.json`. Refresh logic detect expired session and re-login automatically (or alert if 2FA required). Harden browser fingerprint enough to diagnose Google Meet risk-queue outcomes.

## Requirements

**Functional:**
- One-time manual login script: human completes 2FA → save storageState
- Headless re-launch sử dụng saved state
- Detect expired state (login redirect on launch) → trigger re-auth flow
- storageState file encrypted at rest with Fernet

**Non-functional:**
- File permissions 600
- Test session validity via cheap probe (load `myaccount.google.com`)
- Chromium launch includes 2026-level automation risk mitigations: realistic viewport/user-agent, `--disable-blink-features=AutomationControlled`, init script for `navigator.webdriver`, and human-like timing jitter around join steps

## Architecture

```
src/
├── bot/
│   ├── browser_session.py           # Playwright launch + storageState mgmt
│   ├── storage_state_store.py       # encrypt/decrypt storageState
│   └── login_flow.py                # interactive first-login + auto-recover
└── scripts/
    └── bot_first_login.py           # CLI for manual first login
```

## Related Code Files

**Create:**
- `src/bot/__init__.py`
- `src/bot/browser_session.py`
- `src/bot/storage_state_store.py`
- `src/bot/login_flow.py`
- `scripts/bot_first_login.py`

**Modify:**
- `pyproject.toml` (add `playwright`)
- `.env.example` (add `BOT_EMAIL`, `STORAGE_STATE_PATH`, `STORAGE_PASSPHRASE`)

## Implementation Steps

1. `uv add playwright && uv run playwright install chromium --with-deps`
2. `scripts/bot_first_login.py`:
   - Launch Chromium **headed** (not headless)
   - Navigate `accounts.google.com`
   - Wait for human to login + 2FA
   - Detect successful login (URL = `myaccount.google.com` OR similar)
   - Save `storageState()` JSON
   - Encrypt and store at `STORAGE_STATE_PATH`
3. `bot/storage_state_store.py`:
   - `save(state_dict)` → encrypt → write file (chmod 600)
   - `load() -> dict | None`
   - `exists() -> bool`
4. `bot/browser_session.py`:
   - `async launch_with_state() -> (browser, context, page)`:
     - decrypt storageState
     - launch Chromium headless with state
     - apply stealth context settings before first page load:
       - realistic user agent, timezone, locale, viewport, color scheme
       - `--disable-blink-features=AutomationControlled`
       - `add_init_script` to make `navigator.webdriver` non-true without deleting the property
       - randomized waits and mouse movement helpers exposed for join flow
     - return context
5. `bot/login_flow.py`:
   - `async verify_session(context) -> bool`: navigate `myaccount.google.com`, check redirect to login
   - `on_expired()`: log error, write `state=stale` flag, send Telegram alert
6. Document in README: "first-time setup" — run `python scripts/bot_first_login.py` interactively (e.g. via SSH X-forwarding or local Mac)

## Success Criteria

- [ ] First-login script saves state successfully after 2FA
- [ ] Headless launch with saved state lands on `myaccount.google.com` (not login page)
- [ ] State file is encrypted (raw read shows no plaintext cookies)
- [ ] Expired state detected → alert sent
- [ ] Manual test: restart container, headless session still works for ≥24h

## Risk Assessment

- 2FA challenge on headless launch from new IP → mitigate: do first-login on the actual LXC's IP, or use App Passwords (deprecated but works for some setups)
- Google may flag headless Chromium → use realistic user-agent, viewport, `--disable-blink-features=AutomationControlled`, webdriver mitigation, timing jitter, and explicit risk-queue diagnostics in Phase 4
- storageState expiry: Google sessions typically last weeks if remembered; daily verify ping prevents surprise on meeting day
