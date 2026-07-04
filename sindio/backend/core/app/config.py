from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = str(Path(__file__).resolve().parent.parent.parent.parent / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    jwt_secret: str = Field(default="", validation_alias="JWT_SECRET")

    # Database: prefer DATABASE_URL (Railway / Render standard), fall back to components
    database_url_raw: str | None = Field(default=None, validation_alias="DATABASE_URL")
    db_password: str = Field(default="dev-password-change-me", validation_alias="DB_PASSWORD")
    db_host: str = Field(default="localhost", validation_alias="DB_HOST")
    db_port: str = Field(default="5432", validation_alias="DB_PORT")
    db_name: str = Field(default="sindio", validation_alias="DB_NAME")
    db_user: str = Field(default="sindio_user", validation_alias="DB_USER")

    # Redis: prefer REDIS_URL (Railway / Render standard), fall back to components
    redis_url_raw: str | None = Field(default=None, validation_alias="REDIS_URL")
    redis_password: str | None = Field(default=None, validation_alias="REDIS_PASSWORD")
    redis_host: str = Field(default="localhost", validation_alias="REDIS_HOST")
    redis_port: str = Field(default="6379", validation_alias="REDIS_PORT")

    core_port: int = Field(default=8081, validation_alias="CORE_PORT")
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000,http://localhost:4000",
        validation_alias="CORS_ORIGINS",
    )
    alert_sudden_change_threshold: float = Field(default=0.2, validation_alias="ALERT_SUDDEN_CHANGE_THRESHOLD")
    alert_critical_stress_threshold: float = Field(default=0.85, validation_alias="ALERT_CRITICAL_STRESS_THRESHOLD")

    @property
    def port(self) -> int:
        return self.core_port

    @property
    def database_url(self) -> str:
        if self.database_url_raw:
            return self.database_url_raw
        return (
            f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_url_raw:
            return self.redis_url_raw
        auth_part = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth_part}{self.redis_host}:{self.redis_port}/1"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


config = get_settings()
