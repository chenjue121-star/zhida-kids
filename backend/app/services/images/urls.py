import base64
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, status

from ...config import settings

logger = logging.getLogger(__name__)


def _is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"} or host.startswith("192.168.") or host.startswith("10.")


def _public_image_url(photo_url: str) -> str:
    public_base = settings.public_base_url.rstrip("/")
    parsed_public = urlparse(public_base)
    if not parsed_public.scheme or not parsed_public.netloc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请配置可公网访问的 PUBLIC_BASE_URL")

    parsed = urlparse(photo_url)
    if parsed.scheme in {"http", "https"} and not _is_local_url(photo_url):
        return photo_url

    path = parsed.path if parsed.scheme else photo_url
    marker = "/uploads/"
    if marker not in path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持识别已上传图片")

    public_url = f"{public_base}{path[path.find(marker):]}"
    if _is_local_url(public_url):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先启动 ngrok 并配置 PUBLIC_BASE_URL 后再识别")
    return public_url


def _local_upload_path(photo_url: str) -> Path:
    parsed = urlparse(photo_url)
    path = parsed.path if parsed.scheme else photo_url
    marker = "/uploads/"
    if marker not in path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持识别已上传图片")
    filename = path.split(marker, 1)[1]
    if "/" in filename or "\\" in filename or not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片地址无效")
    image_path = Path(settings.upload_dir) / filename
    if not image_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")
    return image_path


def _image_data_url(photo_url: str) -> str:
    image_path = _local_upload_path(photo_url)
    media_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{media_type};base64,{encoded}"


def _ark_image_url_or_data_url(photo_url: str) -> str:
    try:
        return _public_image_url(photo_url)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_400_BAD_REQUEST or not settings.ai_image_data_url_fallback:
            raise
        logger.warning("ark clothing image fallback to data_url: reason=%s", exc.detail)
        return _image_data_url(photo_url)
