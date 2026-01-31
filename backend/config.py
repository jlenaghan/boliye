from pathlib import Path

from pydantic_settings import BaseSettings


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
    debug: bool = False

    model_config = {"env_prefix": "HINDI_SRS_", "env_file": ".env"}


settings = Settings()
