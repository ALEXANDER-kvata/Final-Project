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
    invite_token_expire_minutes: int = 24 * 60

    app_base_url: str = "http://localhost:8000"
    smtp_host: str | None = None
    smtp_port: int = 1025
    email_from: str = "no-reply@project-dashboard.local"

    s3_bucket_name: str = "project-documents"
    aws_region: str = "us-east-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_endpoint_url: str | None = "http://localhost:4566"

    max_project_size_bytes: int = 100 * 1024 * 1024
    max_document_size_bytes: int = 25 * 1024 * 1024
    allowed_document_extensions: str = ".pdf,.docx"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def allowed_document_extension_set(self) -> set[str]:
        return {
            extension.strip().lower()
            for extension in self.allowed_document_extensions.split(",")
            if extension.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
