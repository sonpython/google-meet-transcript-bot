from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    user_email: str = Field(default="user@your-domain.com")
    google_oauth_client_secrets: Path = Field(default=Path("client_secrets.json"))
    token_store_path: Path = Field(default=Path("/data/tokens/user-token.fernet"))
    token_passphrase: str | None = Field(default=None)
    oauth_redirect_port: int = Field(default=8765, ge=1024, le=65535)

    calendar_id: str = Field(default="primary")
    calendar_lookahead_minutes: int = Field(default=60, gt=0)
    calendar_poll_interval_seconds: int = Field(default=300, gt=0)

    db_path: Path = Field(default=Path("/data/meeting-assistant.db"))
    audio_dir: Path = Field(default=Path("/data/audio"))
    audio_source: str = Field(default="meet_capture.monitor")
    max_concurrent_meetings: int = Field(default=3, ge=1, le=10)
    output_dir: Path = Field(default=Path("/data/output"))
    debug_dir: Path = Field(default=Path("/data/debug"))

    bot_email: str = Field(default="bot@your-domain.com")
    bot_display_name: str = Field(default="Meeting Note-taker (bot)")
    bot_headless: bool = Field(default=True)
    storage_state_path: Path = Field(default=Path("/data/tokens/storage-state.fernet"))
    storage_passphrase: str | None = Field(default=None)
    bot_session_keepalive_enabled: bool = Field(default=True)
    bot_session_keepalive_interval_seconds: int = Field(default=60, ge=30)
    test_meet_code: str | None = Field(default=None)

    gemini_api_key: str | None = Field(default=None)
    gemini_model: str = Field(default="gemini-2.5-pro")
    auto_purge_audio: bool = Field(default=False)
    audio_retention_days: int = Field(default=10, ge=0)
    delivery_enabled: bool = Field(default=False)

    telegram_bot_token: str | None = Field(default=None)
    telegram_chat_id: str | None = Field(default=None)

    discord_bot_token: str | None = Field(default=None)
    discord_channel_id: str | None = Field(default=None)

    log_level: str = Field(default="INFO")
    health_notify_enabled: bool = Field(default=False)
    admin_token: str | None = Field(default=None)


def load_settings() -> Settings:
    return Settings()
