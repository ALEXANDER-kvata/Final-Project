from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Project Management Dashboard"
    app_env: str = "local"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/project_dashboard"

    jwt_secret_key: str = Field(default="change-me-in-development", min_length=16)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    s3_bucket_name: str = "project-documents"
    aws_region: str = "us-east-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_endpoint_url: str | None = "http://localhost:4566"

    max_project_size_bytes: int = 100 * 1024 * 1024

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
