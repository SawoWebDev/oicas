"""Environment configuration. Secrets come only from the environment / .env, never from code."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"  # development | production | test
    app_name: str = "OICAS"
    app_timezone: str = "Asia/Manila"
    secret_key: str = "dev-insecure-change-me"
    database_url: str = "sqlite:///./data/oicas.db"
    data_dir: Path = Path("./data")

    # Sessions
    session_hours: int = 10
    session_idle_minutes: int = 120
    cookie_secure: bool = False

    # Odoo (read-only). ODOO_MODE=live talks to Odoo; ODOO_MODE=fake uses the built-in
    # development fixture (clearly labelled in the UI, never for production).
    odoo_mode: str = "fake"
    odoo_url: str = ""
    odoo_db: str = ""
    odoo_sync_login: str = ""
    odoo_sync_api_key: str = ""
    odoo_timeout_seconds: int = 60
    odoo_page_size: int = 1000
    odoo_max_retries: int = 3

    # Optional local break-glass administrator (password stored only as scrypt hash).
    bootstrap_admin_login: str = ""
    bootstrap_admin_password: str = ""

    # Background worker
    sync_interval_minutes: int = 60

    @field_validator("odoo_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in ("live", "fake"):
            raise ValueError("ODOO_MODE must be 'live' or 'fake'")
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    def check_production_safety(self) -> list[str]:
        problems = []
        if self.is_production:
            if self.secret_key.startswith("dev-") or len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be set to a random value of at least 32 characters")
            if self.odoo_mode != "live":
                problems.append("ODOO_MODE must be 'live' in production")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true in production (serve over HTTPS)")
            if self.database_url.startswith("sqlite"):
                problems.append("use PostgreSQL in production")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
