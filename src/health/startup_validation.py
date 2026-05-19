from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    failures: tuple[str, ...]


async def validate_startup(settings, token_store, storage_state_store, gemini_client=None, telegram_client=None):
    failures: list[str] = []
    if not token_store.exists():
        failures.append("calendar token missing")
    if not storage_state_store.exists():
        failures.append("playwright storageState missing")
    if settings.gemini_api_key and gemini_client:
        try:
            await gemini_client.generate_text("Return OK")
        except Exception:
            failures.append("gemini ping failed")
    if settings.telegram_bot_token and telegram_client:
        try:
            await telegram_client.send_text("startup validation")
        except Exception:
            failures.append("telegram ping failed")
    return ValidationResult(not failures, tuple(failures))
