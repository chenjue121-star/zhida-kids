import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..aliyun_vision import classify_clothing, segment_cloth
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..deps import ensure_child_owned, get_owned_clothing
from ..models import Clothing, User
from ..schemas import (
    ClothingCreate,
    ClothingOut,
    ClothingRecognizeIn,
    ClothingRecognizeOut,
    ClothingUpdate,
    ClothingUploadAndRecognizeOut,
)
from ..services.images.urls import _ark_image_url_or_data_url
from ..services.images.storage import _build_filename, _persist_image
from ..services.recognition.normalize import _normalize_recognition, _mock_recognition
from ..services.recognition.prompt import _recognition_prompt
from ..services.recognition.recognize import (
    RecognitionEmptyError,
    RecognitionError,
    recognize_image,
)

router = APIRouter(prefix="/clothing", tags=["clothing"])
logger = logging.getLogger(__name__)

@router.get("", response_model=list[ClothingOut])
def list_clothing(
    child_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Clothing]:
    ensure_child_owned(db, current_user, child_id)
    return list(db.scalars(select(Clothing).where(Clothing.child_id == child_id).order_by(Clothing.created_at.desc())))


@router.post("", response_model=ClothingOut, status_code=status.HTTP_201_CREATED)
def create_clothing(
    payload: ClothingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Clothing:
    ensure_child_owned(db, current_user, payload.child_id)
    item = Clothing(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/recognize", response_model=ClothingRecognizeOut)
async def recognize_clothing(
    payload: ClothingRecognizeIn,
    current_user: User = Depends(get_current_user),
) -> ClothingRecognizeOut:
    if settings.dev_ai_mock:
        return _mock_recognition()
    if not settings.ark_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="未配置 ARK_API_KEY")

    image_url = _ark_image_url_or_data_url(payload.photo_url)
    try:
        return await recognize_image(image_url, _recognition_prompt())
    except RecognitionEmptyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别服务未返回文本") from exc
    except RecognitionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别服务调用失败") from exc


@router.get("/{clothing_id}", response_model=ClothingOut)
def get_clothing(
    clothing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Clothing:
    return get_owned_clothing(db, current_user, clothing_id)


@router.put("/{clothing_id}", response_model=ClothingOut)
def update_clothing(
    clothing_id: int,
    payload: ClothingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Clothing:
    item = get_owned_clothing(db, current_user, clothing_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/{clothing_id}/wear", response_model=ClothingOut)
def mark_worn(
    clothing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Clothing:
    item = get_owned_clothing(db, current_user, clothing_id)
    item.wear_count = (item.wear_count or 0) + 1
    item.last_worn_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{clothing_id}")
def delete_clothing(
    clothing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    item = get_owned_clothing(db, current_user, clothing_id)
    db.delete(item)
    db.commit()
    return {"deleted": True}


# ============================================================
#  上传 → 阿里云抠图 → 阿里云服饰识别
# ============================================================

@router.post("/upload-and-recognize", response_model=ClothingUploadAndRecognizeOut)
async def upload_and_recognize_clothing(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> ClothingUploadAndRecognizeOut:
    """一次性：上传 → 抠图 → 服饰属性识别。

    返回：
        - photo_url  : 原图的可访问地址（COS 或本地 uploads）
        - cutout_url : 抠图后的 PNG 地址
        - recognition: 衣物属性（type / main_color / pattern / season /
                       thickness / style_tags / brand / size / confidence 等）
    """
    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持上传图片")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传内容为空")

    # 推断后缀
    original_name = file.filename or ""
    suffix = Path(original_name).suffix or mimetypes.guess_extension(content_type) or ".jpg"

    # 1) 先保存原图（必须放在可公网访问的位置，便于阿里云后续调用）
    original_filename = _build_filename(current_user.id, suffix)
    original_url, _ = _persist_image(original_filename, raw, content_type, current_user.id)
    logger.info("clothing original uploaded: %s", original_url)

    # 2) 阿里云抠图
    try:
        cutout_bytes = segment_cloth(image_url=original_url)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("aliyun segment failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"抠图失败：{exc.__class__.__name__}",
        ) from exc

    cutout_filename = _build_filename(current_user.id, ".png")
    cutout_url, _ = _persist_image(cutout_filename, cutout_bytes, "image/png", current_user.id)
    logger.info("clothing cutout uploaded: %s", cutout_url)

    # 3) 阿里云服饰属性识别（默认用抠图结果，识别效果更干净）
    try:
        raw_attrs = classify_clothing(image_url=cutout_url)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("aliyun classify failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"服饰属性识别失败：{exc.__class__.__name__}",
        ) from exc

    # 4) 二次规范化：把中文字段映射到我们内部的枚举值
    recognition = _normalize_recognition(raw_attrs)
    recognition.cutout_url = cutout_url

    return ClothingUploadAndRecognizeOut(
        photo_url=original_url,
        cutout_url=cutout_url,
        recognition=recognition,
    )

