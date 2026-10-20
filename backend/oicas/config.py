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
    # Primary database = LIVE data (used when ODOO_MODE=live).
    database_url: str = "sqlite:///./data/oicas.db"
    # Secondary database = DEMO data (used when ODOO_MODE=fake). Never shares data with the primary.
    demo_database_url: str = "sqlite:///./data/oicas_demo.db"
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
    def is_live(self) -> bool:
        return self.odoo_mode == "live"

    @property
    def active_database_url(self) -> str:
        """Live → primary database; demo (fake Odoo) → secondary database."""
        return self.database_url if self.is_live else self.demo_database_url

    @property
    def database_role(self) -> str:
        return "primary" if self.is_live else "demo"

    @property
    def sync_configured(self) -> bool:
        return bool(self.odoo_url and self.odoo_db and self.odoo_sync_login and self.odoo_sync_api_key)

    def check_database_separation(self) -> None:
        """Live and demo data must never share a database."""
        if self.database_url.strip() == self.demo_database_url.strip():
            raise RuntimeError("DATABASE_URL (live/primary) and DEMO_DATABASE_URL (demo/secondary) must be different")
        if self.is_live and not (self.odoo_url and self.odoo_db):
            raise RuntimeError("ODOO_MODE=live needs ODOO_URL and ODOO_DB")

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
