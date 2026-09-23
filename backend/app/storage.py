from datetime import timedelta
from urllib.parse import quote

from minio import Minio
from minio.commonconfig import ComposeSource
from minio.error import S3Error

from .config import get_settings

settings = get_settings()
storage = Minio(
    settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    secure=settings.minio_secure,
)
public_storage = Minio(
    settings.minio_public_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    secure=settings.minio_public_secure if settings.minio_public_secure is not None else settings.minio_secure,
)


def ensure_bucket() -> None:
    if not storage.bucket_exists(settings.minio_bucket):
        storage.make_bucket(settings.minio_bucket)


def presigned_put(object_key: str) -> str:
    return public_storage.presigned_put_object(
        settings.minio_bucket, object_key, expires=timedelta(hours=24)
    )


def uploaded_chunks(prefix: str) -> dict[int, int]:
    chunks: dict[int, int] = {}
    for item in storage.list_objects(settings.minio_bucket, prefix=prefix, recursive=True):
        suffix = item.object_name.removeprefix(prefix)
        if suffix.isdigit():
            chunks[int(suffix)] = item.size
    return chunks


def compose_chunks(object_key: str, chunk_keys: list[str]) -> None:
    storage.compose_object(
        settings.minio_bucket,
        object_key,
        [ComposeSource(settings.minio_bucket, key) for key in chunk_keys],
    )


def delete_chunks(prefix: str) -> None:
    for item in storage.list_objects(settings.minio_bucket, prefix=prefix, recursive=True):
        storage.remove_object(settings.minio_bucket, item.object_name)


def presigned_get(object_key: str, hours: int = 1, download_name: str | None = None) -> str:
    response_headers = None
    if download_name:
        safe_name = download_name.replace("\r", "").replace("\n", "")
        response_headers = {
            "response-content-disposition": f"attachment; filename*=UTF-8''{quote(safe_name)}"
        }
    return public_storage.presigned_get_object(
        settings.minio_bucket,
        object_key,
        expires=timedelta(hours=hours),
        response_headers=response_headers,
    )


def stat_object(object_key: str):
    try:
        return storage.stat_object(settings.minio_bucket, object_key)
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject"}:
            return None
        raise


def read_object(object_key: str, max_bytes: int = 256 * 1024 * 1024) -> bytes:
    stat = storage.stat_object(settings.minio_bucket, object_key)
    if stat.size > max_bytes:
        raise ValueError("标注文件超过在线预览解析限制")
    response = storage.get_object(settings.minio_bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def delete_object(object_key: str) -> None:
    storage.remove_object(settings.minio_bucket, object_key)
