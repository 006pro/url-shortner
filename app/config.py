from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str = ""
    base_url: str = "http://localhost:8000"

    short_code_length: int = 7

    rate_limit_max_requests: int = 10
    rate_limit_window_seconds: int = 60


settings = Settings()
