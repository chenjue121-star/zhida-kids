import mimetypes
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import UploadAsset, User
from ..schemas import UploadOut

router = APIRouter(prefix="/upload", tags=["upload"])


def _build_filename(user_id: int, original_name: str, content_type: str) -> str:
    suffix = Path(original_name or "").suffix
    if not suffix:
        suffix = mimetypes.guess_extension(content_type) or ".jpg"
    return f"{user_id}_{uuid4().hex}{suffix}"


def _save_local(filename: str, content: bytes) -> str:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / filename
    target.write_bytes(content)
    return f"{settings.public_base_url.rstrip('/')}/uploads/{filename}"


def _cos_object_key(filename: str) -> str:
    prefix = (settings.tencent_cos_prefix or "").strip().strip("/")
    return f"{prefix}/{filename}" if prefix else filename


def _cos_public_url(key: str) -> str:
    if settings.tencent_cos_public_base_url:
        return f"{settings.tencent_cos_public_base_url.rstrip('/')}/{key}"
    if not settings.tencent_cos_bucket or not settings.tencent_cos_region:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="未配置腾讯云 COS 访问域名")
    return f"https://{settings.tencent_cos_bucket}.cos.{settings.tencent_cos_region}.myqcloud.com/{key}"


def _save_cos(filename: str, content: bytes, content_type: str) -> tuple[str, str]:
    required = [
        settings.tencent_cos_secret_id,
        settings.tencent_cos_secret_key,
        settings.tencent_cos_region,
        settings.tencent_cos_bucket,
    ]
    if not all(required):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="未配置腾讯云 COS 上传参数")

    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="未安装腾讯云 COS SDK") from exc

    key = _cos_object_key(filename)
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
    return _cos_public_url(key), key


def _save_upload(filename: str, content: bytes, content_type: str) -> tuple[str, str]:
    backend = (settings.upload_backend or "local").lower()
    if backend == "cos":
        return _save_cos(filename, content, content_type)
    if backend != "local":
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="未知上传后端")
    return _save_local(filename, content), filename


@router.post("", response_model=UploadOut)
async def upload_image(
    file: UploadFile = File(...),
    file_hash: str = Form(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadOut:
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持上传图片")

    normalized_hash = (file_hash or "").strip().lower()
    if normalized_hash:
        existing = db.scalar(
            select(UploadAsset).where(UploadAsset.user_id == current_user.id, UploadAsset.file_hash == normalized_hash)
        )
        if existing is not None:
            return UploadOut(url=existing.url, filename=existing.filename, reused=True)

    content = await file.read()
    filename = _build_filename(current_user.id, file.filename or "", content_type)
    url, stored_filename = _save_upload(filename, content, content_type)

    if normalized_hash:
        db.add(
            UploadAsset(
                user_id=current_user.id,
                file_hash=normalized_hash,
                url=url,
                filename=stored_filename,
                content_type=content_type,
                size=len(content),
            )
        )
        db.commit()
    return UploadOut(url=url, filename=stored_filename, reused=False)
