from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_base_url: str = "http://localhost:8080"
    api_base_url: str = "http://localhost:8000/api/v1"
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "cv_archive"
    minio_endpoint: str = "localhost:9000"
    minio_public_endpoint: str = "localhost:9000"
    minio_public_secure: bool | None = None
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "cv-assets"
    minio_secure: bool = False
    storage_data_path: str = "."
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(default="development-secret-change-me-32-bytes")
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    initial_admin_username: str = "admin"
    initial_admin_password: str = "admin"
    max_upload_size_bytes: int = 10 * 1024 * 1024 * 1024
    export_expiry_hours: int = 72
    job_stale_minutes: int = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()
