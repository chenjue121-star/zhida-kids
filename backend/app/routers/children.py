import asyncio
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import Child, User
from ..schemas import ChildAvatarGenerateOut, ChildCreate, ChildOut, ChildUpdate

router = APIRouter(prefix="/children", tags=["children"])
logger = logging.getLogger(__name__)


def get_owned_child(db: Session, user: User, child_id: int) -> Child:
    child = db.scalar(select(Child).where(Child.id == child_id, Child.user_id == user.id))
    if child is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="宝贝不存在")
    return child


def _is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"} or host.startswith("192.168.") or host.startswith("10.")


def _public_upload_url(photo_url: str) -> str:
    public_base = settings.public_base_url.rstrip("/")
    parsed_public = urlparse(public_base)
    if not parsed_public.scheme or not parsed_public.netloc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请配置可公网访问的 PUBLIC_BASE_URL")

    parsed = urlparse(photo_url)
    if parsed.scheme in {"http", "https"} and not _is_local_url(photo_url):
        return photo_url

    path = parsed.path if parsed.scheme else photo_url
    if "/uploads/" not in path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持使用已上传的宝贝照片生成")

    public_url = f"{public_base}{path[path.find('/uploads/'):]}"
    if _is_local_url(public_url):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先启动 ngrok 并配置 PUBLIC_BASE_URL 后再生成")
    return public_url


def _age_text(birthday: date) -> str:
    today = date.today()
    months = (today.year - birthday.year) * 12 + today.month - birthday.month
    if today.day < birthday.day:
        months -= 1
    months = max(months, 0)
    years = months // 12
    remain_months = months % 12
    if years:
        return f"{years}岁{remain_months}个月"
    return f"{remain_months}个月"


def _gender_label(gender: str) -> str:
    return "男孩" if gender == "boy" else "女孩"


def _avatar_prompt(child: Child) -> str:
    return (
        "请参考输入的宝贝照片，生成一张儿童穿搭试穿形象图。"
        "尽量保留宝贝的年龄感、发型、脸型气质、肤色倾向和亲和表情，但不要求与本人百分百一致。\n\n"
        "人物信息：\n"
        f"- 昵称：{child.nickname}\n"
        f"- 性别：{_gender_label(child.gender)}\n"
        f"- 年龄：{_age_text(child.birthday)}\n"
        f"- 肤色倾向：{child.skin_tone or '自然'}\n\n"
        "画面要求：\n"
        "一个可爱的 3D 插画风儿童虚拟模特，正面全身站姿，自然微笑，五官圆润，大眼睛，比例适合 0-6 岁儿童穿搭展示。\n"
        "人物穿简洁基础款浅色衣服，服装不要抢眼，方便后续作为穿搭推荐试穿形象。\n"
        "背景是温柔的儿童穿搭试衣舞台，奶油白、浅草绿、浅蓝天光，柔和自然光，有轻微太阳、云朵、圆拱或植物装饰。\n"
        "整体风格干净、温暖、童趣、精致，接近高质量儿童穿搭 App 首页视觉。\n\n"
        "构图要求：\n"
        "1:1 画幅，人物居中，全身完整出现，从头到脚无遮挡。\n"
        "不要裁切头部、脚部，不要多人，不要文字，不要水印，不要品牌 logo。\n"
        "画面留有干净背景，适合在小程序首页和宝贝档案页展示。\n\n"
        "安全要求：\n"
        "儿童友好，非性感化，非成人化，不暴露，不怪异，不恐怖。"
    )


def _collect_image_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        if value.startswith("http://") or value.startswith("https://"):
            urls.append(value)
        return urls
    if isinstance(value, list):
        for item in value:
            urls.extend(_collect_image_urls(item))
        return urls
    if isinstance(value, dict):
        for key in ("url", "image", "image_url", "output", "outputs"):
            if key in value:
                urls.extend(_collect_image_urls(value[key]))
        if "urls" in value:
            urls.extend(_collect_image_urls(value["urls"]))
        if "data" in value:
            urls.extend(_collect_image_urls(value["data"]))
    return urls


def _compact_image_request(request_body: dict[str, Any]) -> dict[str, Any]:
    compact = dict(request_body)
    prompt = compact.get("prompt")
    if isinstance(prompt, str) and len(prompt) > 3000:
        compact["prompt"] = f"{prompt[:3000]}..."
    compact["images"] = [
        f"{url[:160]}..." if isinstance(url, str) and len(url) > 160 else url
        for url in compact.get("images") or []
    ]
    return compact


async def _poll_image_result(client: httpx.AsyncClient, result_url: str) -> str:
    for attempt in range(settings.gptsapi_image_poll_max_attempts):
        response = await client.get(
            result_url,
            headers={"Authorization": f"Bearer {settings.gptsapi_api_key}"},
        )
        logger.warning("gptsapi image poll attempt=%s status_code=%s", attempt + 1, response.status_code)
        logger.warning("gptsapi image poll response=%s", response.text[:2000])
        response.raise_for_status()
        data = response.json()
        status_value = str((data.get("data") or {}).get("status") or data.get("status") or "").lower()
        image_urls = _collect_image_urls(data)
        image_urls = [url for url in image_urls if "/predictions/" not in url or "/result" not in url]
        if image_urls:
            return image_urls[0]
        if status_value in {"failed", "error", "canceled", "cancelled"}:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 虚拟形象生成失败")
        await asyncio.sleep(settings.gptsapi_image_poll_interval)
    raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="AI 虚拟形象生成超时")


async def _download_avatar(client: httpx.AsyncClient, image_url: str, child_id: int) -> str:
    response = await client.get(image_url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 生成结果不是图片")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = f".{settings.gptsapi_image_output_format.lower().lstrip('.') or 'png'}"
    filename = f"avatar_{child_id}_{int(datetime.utcnow().timestamp())}{suffix}"
    target = upload_dir / filename
    target.write_bytes(response.content)
    return f"{settings.public_base_url.rstrip('/')}/uploads/{filename}"


async def _generate_avatar_image(child: Child) -> ChildAvatarGenerateOut:
    if not settings.gptsapi_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="未配置 GPTSAPI_API_KEY")

    public_photo_url = _public_upload_url(child.photo_url)
    prompt = _avatar_prompt(child)
    request_body = {
        "prompt": prompt,
        "images": [public_photo_url],
        "output_format": settings.gptsapi_image_output_format,
    }
    logger.warning("gptsapi image create request=%s", json.dumps(_compact_image_request(request_body), ensure_ascii=False))

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                settings.gptsapi_image_edit_url,
                headers={
                    "Authorization": f"Bearer {settings.gptsapi_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            logger.warning("gptsapi image create status_code=%s", response.status_code)
            logger.warning("gptsapi image create response=%s", response.text[:2000])
            response.raise_for_status()
            data = response.json()
            result_id = (data.get("data") or {}).get("id")
            result_url = ((data.get("data") or {}).get("urls") or {}).get("get") or (data.get("urls") or {}).get("get")
            if not result_url:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 生成服务未返回结果地址")
            logger.warning("gptsapi image result_id=%s result_url=%s", result_id, result_url)
            image_url = await _poll_image_result(client, result_url)
            avatar_url = await _download_avatar(client, image_url, child.id)
    except httpx.HTTPStatusError as exc:
        logger.warning("gptsapi image http error=%s", exc.response.text[:1000])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 虚拟形象服务调用失败") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 虚拟形象服务调用失败") from exc

    result = ChildAvatarGenerateOut(
        avatar_url=avatar_url,
        prompt=prompt,
        status="succeeded",
        message="AI 会参考宝贝照片生成儿童试穿形象，尽量保留年龄感、发型、脸型气质和肤色特征，但生成结果可能与本人存在差异。你可以重新生成或继续使用宝贝照片。",
    )
    logger.warning("gptsapi image normalized=%s", result.model_dump_json())
    return result


@router.get("", response_model=list[ChildOut])
def list_children(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Child]:
    return list(db.scalars(select(Child).where(Child.user_id == current_user.id).order_by(Child.created_at)))


@router.post("", response_model=ChildOut, status_code=status.HTTP_201_CREATED)
def create_child(
    payload: ChildCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Child:
    child = Child(user_id=current_user.id, **payload.model_dump())
    db.add(child)
    db.commit()
    db.refresh(child)
    return child


@router.put("/{child_id}", response_model=ChildOut)
def update_child(
    child_id: int,
    payload: ChildUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Child:
    child = get_owned_child(db, current_user, child_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(child, field, value)
    db.commit()
    db.refresh(child)
    return child


@router.post("/{child_id}/avatar/generate", response_model=ChildAvatarGenerateOut)
async def generate_child_avatar(
    child_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChildAvatarGenerateOut:
    child = get_owned_child(db, current_user, child_id)
    if not child.photo_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先上传宝贝照片")

    if settings.dev_ai_mock:
        prompt = _avatar_prompt(child)
        child.avatar_url = child.avatar_url or child.photo_url
        db.commit()
        db.refresh(child)
        return ChildAvatarGenerateOut(
            avatar_url=child.avatar_url,
            prompt=prompt,
            status="mock",
            message="开发 mock：已使用宝贝照片作为试穿形象占位。",
        )

    result = await _generate_avatar_image(child)
    child.avatar_url = result.avatar_url
    db.commit()
    db.refresh(child)
    return result


@router.delete("/{child_id}")
def delete_child(
    child_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    child = get_owned_child(db, current_user, child_id)
    db.delete(child)
    db.commit()
    return {"deleted": True}
