from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jev_api_key: str
    jev_base_url: str = "https://api.typesafe.ai/v1"
    jev_timeout_seconds: float = 5.0

    llm_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-6"


settings = Settings()
