from datetime import UTC, datetime
from pathlib import Path

from pydantic_settings import BaseSettings


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime.

    Replaces the deprecated ``datetime.utcnow()`` while keeping datetimes
    naive so they stay compatible with SQLite (which doesn't store tz info).
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Settings(BaseSettings):
    app_name: str = "Hindi SRS"
    database_url: str = f"sqlite+aiosqlite:///{Path(__file__).resolve().parent.parent / 'data' / 'hindi_srs.db'}"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_retries: int = 3
    anthropic_rate_limit_rpm: int = 50
    target_retention: float = 0.9
    max_new_cards_per_session: int = 10
    max_reviews_per_session: int = 20
    llm_input_price_per_million: float = 3.0
    llm_output_price_per_million: float = 15.0
    session_ttl_seconds: int = 7200  # 2 hours
    debug: bool = False

    model_config = {"env_prefix": "HINDI_SRS_", "env_file": ".env"}


settings = Settings()
