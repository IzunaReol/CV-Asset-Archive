from app.config import Settings


def test_development_allows_local_defaults():
    assert Settings(_env_file=None, app_env="development").deployment_security_errors() == []


def test_production_rejects_default_credentials():
    errors = Settings(_env_file=None, app_env="production").deployment_security_errors()
    assert "JWT_SECRET 必须为至少 32 字符的非默认值" in errors
    assert "INITIAL_ADMIN_PASSWORD 必须为至少 12 字符的非默认值" in errors
    assert "MINIO_ACCESS_KEY 必须为至少 3 字符的非默认值" in errors
    assert "MINIO_SECRET_KEY 必须为至少 12 字符的非默认值" in errors


def test_production_rejects_blank_or_short_credentials():
    errors = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="short",
        initial_admin_password="",
        minio_access_key="",
        minio_secret_key="short",
    ).deployment_security_errors()
    assert len(errors) == 4


def test_production_rejects_example_admin_password():
    errors = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="a-long-random-secret-that-is-not-the-default",
        initial_admin_password="replace-with-a-strong-password",
        minio_access_key="archive-service",
        minio_secret_key="a-strong-minio-secret",
    ).deployment_security_errors()
    assert errors == ["INITIAL_ADMIN_PASSWORD 必须为至少 12 字符的非默认值"]


def test_production_accepts_replaced_credentials():
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="a-long-random-secret-that-is-not-the-default",
        initial_admin_password="strong-admin-password",
        minio_access_key="archive-service",
        minio_secret_key="a-strong-minio-secret",
    )
    assert settings.deployment_security_errors() == []
