"""Application-wide configuration via pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global application settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- General ---
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # --- Server ---
    host: str = "0.0.0.0"  # noqa: S104  # intentional for Docker / dev
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # --- DuckDB ---
    duckdb_memory_limit: str = "4GB"
    duckdb_threads: int = 4

    # --- Credential Encryption ---
    encryption_key: str = ""  # Fernet key; auto-generated on first run if empty

    # --- Upload ---
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 500

    # --- Serving Gateways ---
    enable_pgwire: bool = True
    pgwire_host: str = "0.0.0.0"  # noqa: S104
    pgwire_port: int = 5433

    enable_flight: bool = True
    flight_host: str = "0.0.0.0"  # noqa: S104
    flight_port: int = 5005


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
