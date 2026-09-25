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

    def deployment_security_errors(self) -> list[str]:
        if self.app_env.lower() in {"development", "test", "local"}:
            return []
        errors: list[str] = []
        if len(self.jwt_secret.strip()) < 32 or self.jwt_secret in {"development-secret-change-me-32-bytes", "replace-with-at-least-32-random-bytes"}:
            errors.append("JWT_SECRET 必须为至少 32 字符的非默认值")
        if len(self.initial_admin_password.strip()) < 12 or self.initial_admin_password in {"admin", "replace-me", "replace-with-a-strong-password"}:
            errors.append("INITIAL_ADMIN_PASSWORD 必须为至少 12 字符的非默认值")
        if len(self.minio_access_key.strip()) < 3 or self.minio_access_key in {"minioadmin", "replace-me"}:
            errors.append("MINIO_ACCESS_KEY 必须为至少 3 字符的非默认值")
        if len(self.minio_secret_key.strip()) < 12 or self.minio_secret_key in {"minioadmin", "replace-me"}:
            errors.append("MINIO_SECRET_KEY 必须为至少 12 字符的非默认值")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
