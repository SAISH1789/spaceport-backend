from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://spaceport:spaceport@localhost:5432/spaceport"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_key_prefix: str = "spaceport"
    ships_cache_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    cors_origins: list[str] = ["http://localhost:5173"]
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
