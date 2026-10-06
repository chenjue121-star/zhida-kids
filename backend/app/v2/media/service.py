from __future__ import annotations

import hashlib
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from app.v2.core.errors import fail


IMAGE_FORMATS = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}
MAX_IMAGE_PIXELS = 24_000_000
THUMBNAIL_MAX_EDGE = 360


def normalize_image(raw: bytes, content_type: str, max_bytes: int = 12 * 1024 * 1024):
    """Verify the decoded image and strip metadata before hashing stored bytes."""
    if len(raw) > max_bytes:
        fail(413, 'IMAGE_TOO_LARGE', '照片过大，请选择不超过限制的照片')
    mime = content_type.split(';', 1)[0].strip().lower()
    if not raw or mime not in IMAGE_FORMATS:
        fail(422, 'INVALID_IMAGE', '请选择 JPEG、PNG 或 WebP 照片')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                if probe.format != IMAGE_FORMATS[mime]:
                    fail(422, 'INVALID_IMAGE', '照片格式与声明不一致')
                if probe.width * probe.height > MAX_IMAGE_PIXELS:
                    fail(413, 'IMAGE_TOO_LARGE', '照片分辨率过大，请缩小后重试')
                if getattr(probe, 'n_frames', 1) != 1:
                    fail(422, 'INVALID_IMAGE', '请选择单张静态照片')
                probe.verify()
            # verify() invalidates its image; reopening and loading also catches
            # malformed pixel streams that a header-only check would accept.
            with Image.open(io.BytesIO(raw)) as source:
                source.load()
                oriented = ImageOps.exif_transpose(source)
                if oriented.mode in ('RGBA', 'LA') or 'transparency' in oriented.info:
                    rgba = oriented.convert('RGBA')
                    rgb = Image.new('RGB', rgba.size, 'white')
                    rgb.paste(rgba, mask=rgba.getchannel('A'))
                else:
                    rgb = oriented.convert('RGB')
                clean = Image.new('RGB', rgb.size)
                clean.paste(rgb)
                output = io.BytesIO()
                clean.save(output, format='JPEG', quality=90, optimize=True)
                normalized = output.getvalue()
                if len(normalized) > max_bytes:
                    fail(413, 'IMAGE_TOO_LARGE', '处理后的照片过大，请缩小后重试')
                return normalized, hashlib.sha256(normalized).hexdigest(), clean.width, clean.height
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        fail(413, 'IMAGE_TOO_LARGE', '照片分辨率过大，请缩小后重试')
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        fail(422, 'INVALID_IMAGE', '照片无法读取，请重新拍摄或选择其他照片')


def thumbnail_image(content: bytes) -> bytes:
    """Return a metadata-free list preview without changing the stored image."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    fail(404, 'NOT_FOUND', '图片暂不可用')
                source.load()
                oriented = ImageOps.exif_transpose(source)
                oriented.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), Image.Resampling.LANCZOS)
                if oriented.mode in ('RGBA', 'LA') or 'transparency' in oriented.info:
                    rgba = oriented.convert('RGBA')
                    rgb = Image.new('RGB', rgba.size, 'white')
                    rgb.paste(rgba, mask=rgba.getchannel('A'))
                else:
                    rgb = oriented.convert('RGB')
                clean = Image.new('RGB', rgb.size)
                clean.paste(rgb)
                output = io.BytesIO()
                clean.save(output, format='JPEG', quality=80, optimize=True)
                return output.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning,
            UnidentifiedImageError, OSError, ValueError, SyntaxError):
        fail(404, 'NOT_FOUND', '图片暂不可用')
