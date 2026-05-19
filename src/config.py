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
    log_level: str = Field(default="INFO")


def load_settings() -> Settings:
    return Settings()
