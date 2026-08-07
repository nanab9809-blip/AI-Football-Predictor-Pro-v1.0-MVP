from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "AI Football Predictor Pro"
    app_env: str = "production"
    secret_key: str = "change-this-secret-key"
    admin_username: str = "admin"
    admin_password: str = "admin123"
    api_football_key: str = ""
    api_football_base_url: str = "https://v3.football.api-sports.io"
    timezone: str = "Asia/Makassar"
    cache_ttl_seconds: int = 300
    database_path: str = "storage/football_predictor.db"
    database_url: str = ""
    min_confidence: float = 62.0
    min_ev: float = 0.03
    paper_bankroll: float = 100.0
    automation_enabled: bool = True
    settlement_interval_minutes: int = 30

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def api_configured(self) -> bool:
        return bool(self.api_football_key.strip())

    @property
    def database_file(self) -> Path:
        path = Path(self.database_path)
        return path if path.is_absolute() else BASE_DIR / path

    @property
    def resolved_database_url(self) -> str:
        raw_url = self.database_url.strip()
        if raw_url:
            # Render may provide either postgres:// or postgresql://.
            # Explicitly select the Psycopg 3 SQLAlchemy dialect so SQLAlchemy
            # does not fall back to the legacy psycopg2 driver.
            if raw_url.startswith("postgres://"):
                return raw_url.replace("postgres://", "postgresql+psycopg://", 1)
            if raw_url.startswith("postgresql://"):
                return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
            return raw_url
        return f"sqlite:///{self.database_file.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
