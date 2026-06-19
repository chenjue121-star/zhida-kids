from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from ...config import settings


def _cos_upload(filename: str, content: bytes, content_type: str) -> str:
    """把内容上传到腾讯云 COS，返回可公网访问的 URL。"""
    if not (settings.tencent_cos_secret_id and settings.tencent_cos_secret_key
            and settings.tencent_cos_region and settings.tencent_cos_bucket):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="使用阿里云抠图/识别 时需配置腾讯云 COS 以便生成公网图片 URL",
        )
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="未安装腾讯云 COS SDK",
        ) from exc

    prefix = (settings.tencent_cos_prefix or "").strip().strip("/")
    key = f"{prefix}/{filename}" if prefix else filename
    config = CosConfig(
        Region=settings.tencent_cos_region,
        SecretId=settings.tencent_cos_secret_id,
        SecretKey=settings.tencent_cos_secret_key,
        Scheme="https",
    )
    client = CosS3Client(config)
    client.put_object(
        Bucket=settings.tencent_cos_bucket,
        Body=BytesIO(content),
        Key=key,
        ContentType=content_type,
    )
    if settings.tencent_cos_public_base_url:
        return f"{settings.tencent_cos_public_base_url.rstrip('/')}/{key}"
    return f"https://{settings.tencent_cos_bucket}.cos.{settings.tencent_cos_region}.myqcloud.com/{key}"


def _local_persist(filename: str, content: bytes) -> str:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / filename).write_bytes(content)
    return f"{settings.public_base_url.rstrip('/')}/uploads/{filename}"


def _persist_image(
    filename: str,
    content: bytes,
    content_type: str,
    user_id: int,
) -> tuple[str, str]:
    """保存图片，返回 (public_url, stored_filename)。

    如果后端为 COS，则上传到 COS 并返回公网 URL；
    否则保存到本地 uploads，并返回 PUBLIC_BASE_URL 拼接的地址（便于本地调试）。
    """
    backend = (settings.upload_backend or "local").lower()
    if backend == "cos":
        url = _cos_upload(filename, content, content_type)
        return url, filename
    url = _local_persist(filename, content)
    return url, filename


def _build_filename(user_id: int, suffix: str) -> str:
    return f"{user_id}_{uuid4().hex}{suffix}"
