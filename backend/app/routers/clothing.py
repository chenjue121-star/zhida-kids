import base64
import json
import logging
import mimetypes
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Union
from uuid import uuid4
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..aliyun_vision import classify_clothing, segment_cloth
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import Child, Clothing, User
from ..schemas import (
    ClothingCreate,
    ClothingOut,
    ClothingRecognizeIn,
    ClothingRecognizeOut,
    ClothingUpdate,
    ClothingUploadAndRecognizeOut,
)

router = APIRouter(prefix="/clothing", tags=["clothing"])
logger = logging.getLogger(__name__)

CLOTHING_TYPES = [
    "top", "pants", "skirt", "outerwear", "shoes", "hat", "accessory", "set", "innerwear", "babywear", "sleepwear",
]
CLOTHING_SUB_TYPES = [
    "tshirt", "shirt", "hoodie", "sweater", "polo", "vest", "jeans", "casual_pants", "shorts", "sweatpants",
    "leggings", "bib_pants", "sock_pants", "short_skirt", "long_skirt", "dress", "tutu", "jacket",
    "down_jacket", "windbreaker", "cardigan", "coat", "cape", "sneakers", "sandals", "boots", "casual_shoes",
    "slippers", "toddler_shoes", "crib_shoes", "cap", "bucket_hat", "beanie", "sun_hat", "scarf", "gloves",
    "bag", "hairband", "socks", "bib", "feeding_bib", "burp_cloth", "blanket", "casual_set", "sport_set",
    "formal_set", "thermal", "undershirt", "onesie", "romper", "bodysuit", "coverall", "swaddle", "pajamas",
    "sleep_sack", "robe",
]
COLORS = [
    "white", "black", "gray", "red", "orange", "yellow", "green", "blue", "purple", "pink", "peach", "mint",
    "sky_blue", "lavender", "cream", "beige", "khaki", "brown", "coffee", "navy", "burgundy", "forest_green",
    "charcoal", "denim", "gold", "silver", "neon_green", "multicolor",
]
PATTERNS = [
    "solid", "stripe", "plaid", "print", "cartoon", "floral", "polka_dot", "animal", "letter", "number",
    "star", "heart", "cloud", "rainbow", "dinosaur", "car", "embroidery", "colorblock", "gradient", "contrast",
    "leopard",
]
SEASONS = ["spring", "summer", "autumn", "winter", "all"]
THICKNESS = ["thin", "normal", "thick", "fleece"]
STYLE_TAGS = ["casual", "sporty", "formal", "cute", "cool", "korean", "japanese", "preppy", "minimalist"]
RECOGNITION_FIELD_SCORE_META = {
    "type": {"category": "required", "weight": 28},
    "main_color": {"category": "required", "weight": 20},
    "thickness": {"category": "required", "weight": 18},
    "pattern": {"category": "optional", "weight": 10},
    "style_tags": {"category": "optional", "weight": 10},
    "season": {"category": "optional", "weight": 8},
    "sub_type": {"category": "optional", "weight": 4},
    "brand": {"category": "informational", "weight": 2},
    "size": {"category": "informational", "weight": 2},
}

def ensure_child_owned(db: Session, user: User, child_id: int) -> Child:
    child = db.scalar(select(Child).where(Child.id == child_id, Child.user_id == user.id))
    if child is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="宝贝不存在")
    return child


def get_owned_clothing(db: Session, user: User, clothing_id: int) -> Clothing:
    item = db.scalar(
        select(Clothing)
        .join(Child, Clothing.child_id == Child.id)
        .where(Clothing.id == clothing_id, Child.user_id == user.id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="衣物不存在")
    return item


def _mock_recognition() -> ClothingRecognizeOut:
    return ClothingRecognizeOut(
        type="accessory",
        sub_type="bib",
        main_color="cream",
        pattern="cartoon",
        season=["all"],
        thickness="normal",
        style_tags=["cute"],
        confidence=0.72,
        notes="开发 mock：请根据实物确认字段。",
    )


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


def _compact_ark_request(request_body: dict[str, Any]) -> dict[str, Any]:
    compact = json.loads(json.dumps(request_body, ensure_ascii=False))
    for item in compact.get("input") or []:
        for block in item.get("content") or []:
            image_url = block.get("image_url")
            if isinstance(image_url, str) and image_url.startswith("data:"):
                header = image_url.split(",", 1)[0]
                block["image_url"] = f"{header},<base64 {len(image_url)} chars>"
            text = block.get("text")
            if isinstance(text, str) and len(text) > 3000:
                block["text"] = f"{text[:3000]}..."
    return compact


def _extract_json(text: str) -> Union[dict, list]:
    cleaned = text.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 未返回识别结果")

    # 去除 markdown code fence
    lines = cleaned.splitlines()
    if lines and lines[0].strip().startswith("```"):
        stripped_lines = []
        in_fence = False
        fence_start_seen = False
        for line in lines:
            if line.strip().startswith("```"):
                if not fence_start_seen:
                    in_fence = True
                    fence_start_seen = True
                else:
                    in_fence = False
                continue
            if fence_start_seen and not in_fence:
                break
            if fence_start_seen or not line.strip().startswith("```"):
                stripped_lines.append(line)
        cleaned = "\n".join(stripped_lines).strip()

    # 查找第一个 { 或 [
    obj_start = cleaned.find("{")
    arr_start = cleaned.find("[")
    start_idx = -1
    if obj_start >= 0 and (arr_start < 0 or obj_start < arr_start):
        start_idx = obj_start
        end_marker = "}"
    elif arr_start >= 0:
        start_idx = arr_start
        end_marker = "]"
    else:
        logger.warning("AI 识别结果不含 JSON: raw_text=%r", text[:500])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别结果不是合法 JSON")

    # 从 start_idx 开始搜索匹配的右括号
    depth = 0
    in_string = False
    escape_next = False
    end_idx = -1
    for i in range(start_idx, len(cleaned)):
        ch = cleaned[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{" or ch == "[":
            depth += 1
        elif ch == "}" or ch == "]":
            depth -= 1
            if depth == 0 and (end_marker == ch or (end_marker == "}" and ch == "}") or (end_marker == "]" and ch == "]")):
                end_idx = i + 1
                break
    if end_idx <= start_idx:
        logger.warning("AI 识别 JSON 括号不匹配: raw_text=%r", text[:500])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别结果不是合法 JSON")

    candidate = cleaned[start_idx:end_idx]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning("AI JSON parse failed: error=%s candidate=%r", str(exc), candidate[:500])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别结果不是合法 JSON") from exc

def _extract_ark_text(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    texts: list[str] = []

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(value, str):
            return
        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return
        if not isinstance(value, dict):
            return

        out_text = value.get("output_text")
        if isinstance(out_text, str) and out_text and out_text not in texts:
            texts.append(out_text)

        for text_key in ("text", "content", "message"):
            v = value.get(text_key)
            if isinstance(v, str) and v and v not in texts:
                texts.append(v)

        for nested_key in ("output", "data", "choices", "candidates"):
            if nested_key in value:
                walk(value[nested_key], depth + 1)

        # 兼容 openai-style: choices -> message -> content
        choices = value.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict):
                    msg = choice.get("message") or choice.get("delta")
                    if isinstance(msg, dict):
                        content = msg.get("content")
                        if isinstance(content, str) and content and content not in texts:
                            texts.append(content)

    walk(data)
    combined = "\n".join(t for t in texts if t).strip()
    if combined:
        return combined

    # 终极兜底：如果没找到结构化的文本字段，尝试对整个响应做 json.dumps 后搜索
    try:
        raw = json.dumps(data, ensure_ascii=False)
        if len(raw) > 300:
            return ""
    except Exception:
        return ""
    return ""

def _pick_recognition_object(parsed: Union[dict, list]) -> dict:
    if isinstance(parsed, dict):
        if "type" in parsed or "main_color" in parsed or "category" in parsed:
            return parsed
        # 对象是包裹的，从常见 key 中搜索
        for key in ("result", "data", "item", "item_info", "clothing", "recognition"):
            value = parsed.get(key)
            if isinstance(value, dict):
                return _pick_recognition_object(value)
        return parsed

    if not isinstance(parsed, list):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别结果不是对象")

    candidates = [item for item in parsed if isinstance(item, dict)]
    if not candidates:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别结果为空")

    def score_candidate(c: dict) -> float:
        s = 0.0
        for key in ("type", "category", "main_color", "color", "categoryPrimary"):
            if c.get(key):
                s += 1.0
        try:
            s += float(c.get("confidence") or 0) * 2
        except (TypeError, ValueError):
            pass
        return s

    selected = max(candidates, key=score_candidate)
    note = "识别到多件衣物，已优先选择信息最完整的一件，请确认或手动调整。"
    existing_notes = selected.get("notes") or ""
    selected["notes"] = f"{note} {existing_notes}".strip()
    return selected


_TYPE_ALIAS: dict[str, str] = {
    "上衣": "top", "t恤": "top", "tee": "top", "衬衫": "top", "毛衣": "top", "卫衣": "top",
    "马甲": "top", "背心": "top",
    "裤子": "pants", "裤": "pants", "牛仔裤": "pants", "长裤": "pants",
    "短裤": "pants", "运动裤": "pants", "打底裤": "pants",
    "裙子": "skirt", "裙": "skirt", "短裙": "skirt", "长裙": "skirt",
    "外套": "outerwear", "夹克": "outerwear", "羽绒服": "outerwear", "大衣": "outerwear",
    "风衣": "outerwear",
    "鞋子": "shoes", "鞋": "shoes", "运动鞋": "shoes", "凉鞋": "shoes", "靴子": "shoes",
    "学步鞋": "shoes", "拖鞋": "shoes",
    "帽子": "hat", "帽": "hat",
    "配饰": "accessory", "配件": "accessory", "围巾": "accessory", "手套": "accessory",
    "包": "accessory", "包包": "accessory", "发带": "accessory", "袜子": "accessory",
    "围兜": "accessory", "口水巾": "accessory",
    "套装": "set", "两件套": "set", "三件套": "set",
    "内衣": "innerwear", "秋衣": "innerwear", "秋裤": "innerwear",
    "婴儿服": "babywear", "连体衣": "babywear", "哈衣": "babywear", "爬服": "babywear",
    "睡衣": "sleepwear", "睡袋": "sleepwear",
}

_COLOR_ALIAS: dict[str, str] = {
    "白": "white", "白色": "white", "米白": "white",
    "黑": "black", "黑色": "black",
    "灰": "gray", "灰色": "gray", "浅灰": "gray", "深灰": "gray",
    "红": "red", "红色": "red", "大红": "red",
    "橙": "orange", "橙色": "orange", "橘": "orange", "橘色": "orange",
    "黄": "yellow", "黄色": "yellow", "金黄": "yellow",
    "绿": "green", "绿色": "green", "草绿": "green", "浅绿": "green",
    "蓝": "blue", "蓝色": "blue", "深蓝": "blue", "浅蓝": "blue",
    "紫": "purple", "紫色": "purple",
    "粉": "pink", "粉色": "pink", "粉红": "pink", "浅粉": "pink",
    "桃色": "peach", "桃粉": "peach",
    "薄荷": "mint", "薄荷绿": "mint",
    "天蓝": "sky_blue", "天空蓝": "sky_blue", "湖蓝": "sky_blue",
    "淡紫": "lavender", "薰衣草": "lavender", "浅紫": "lavender",
    "奶油": "cream", "奶油色": "cream",
    "米色": "beige", "米": "beige",
    "卡其": "khaki", "卡其色": "khaki",
    "棕": "brown", "棕色": "brown", "深棕": "brown",
    "咖啡": "coffee", "咖啡色": "coffee",
    "藏青": "navy", "藏蓝": "navy", "深蓝": "navy", "藏青色": "navy",
    "酒红": "burgundy", "酒红色": "burgundy", "枣红": "burgundy",
    "森林绿": "forest_green", "墨绿": "forest_green",
    "炭灰": "charcoal", "炭黑": "charcoal",
    "牛仔": "denim", "牛仔蓝": "denim",
    "金": "gold", "金色": "gold",
    "银": "silver", "银色": "silver",
    "荧光绿": "neon_green", "亮绿": "neon_green",
    "多色": "multicolor", "花色": "multicolor", "彩色": "multicolor", "印花": "multicolor",
}

_PATTERN_ALIAS: dict[str, str] = {
    "纯色": "solid", "素色": "solid",
    "条纹": "stripe", "横条纹": "stripe", "竖条纹": "stripe",
    "格纹": "plaid", "格子": "plaid", "格": "plaid", "格仔": "plaid",
    "图案": "print", "印花": "print",
    "卡通": "cartoon", "卡通人物": "cartoon", "动漫": "cartoon",
    "花朵": "floral", "碎花": "floral", "花": "floral",
    "波点": "polka_dot", "圆点": "polka_dot",
    "动物": "animal",
    "字母": "letter", "字母印花": "letter",
    "数字": "number",
    "星星": "star", "五角星": "star",
    "爱心": "heart", "心形": "heart",
    "云朵": "cloud", "白云": "cloud",
    "彩虹": "rainbow",
    "恐龙": "dinosaur",
    "汽车": "car", "小汽车": "car",
    "刺绣": "embroidery", "绣花": "embroidery",
    "撞色": "colorblock", "色块": "colorblock", "拼接": "colorblock",
    "渐变": "gradient", "渐变色": "gradient",
    "撞色拼接": "contrast",
    "豹纹": "leopard", "动物纹": "leopard",
}

_THICKNESS_ALIAS: dict[str, str] = {
    "薄": "thin", "薄款": "thin", "单层": "thin", "网眼": "thin", "夏季": "thin",
    "普通": "normal", "常规": "normal", "中等": "normal", "春秋": "normal",
    "厚": "thick", "厚款": "thick", "双层": "thick", "夹棉": "thick", "冬季": "thick",
    "加绒": "fleece", "抓绒": "fleece", "摇粒绒": "fleece", "羊羔绒": "fleece",
    "绒": "fleece",
}

_SEASON_ALIAS: dict[str, str] = {
    "春": "spring", "春季": "spring",
    "夏": "summer", "夏季": "summer",
    "秋": "autumn", "秋季": "autumn",
    "冬": "winter", "冬季": "winter",
    "全年": "all", "四季": "all", "通用": "all",
}

_STYLE_ALIAS: dict[str, str] = {
    "休闲": "casual", "日常": "casual",
    "运动": "sporty", "运动风": "sporty",
    "正式": "formal", "礼服": "formal",
    "可爱": "cute", "甜美": "cute",
    "酷": "cool", "酷帅": "cool", "潮": "cool",
    "韩系": "korean", "韩版": "korean", "韩风": "korean",
    "日系": "japanese", "日版": "japanese", "和风": "japanese",
    "学院": "preppy", "学院风": "preppy", "校园": "preppy",
    "简约": "minimalist", "简约风": "minimalist", "极简": "minimalist",
}


def _normalize_recognition(data: dict) -> ClothingRecognizeOut:
    def pick(value: Any, allowed: list[str], alias_map: dict[str, str], default: str) -> str:
        if value is None:
            return default
        if not isinstance(value, str):
            value = str(value)
        v = value.strip()
        if not v:
            return default
        lowered = v.lower()
        # 1. 精确匹配枚举（大小写不敏感）
        for a in allowed:
            if a.lower() == lowered:
                return a
        # 2. 别名精确匹配（中文）
        if v in alias_map:
            return alias_map[v]
        alias_lowered = {k.lower(): val for k, val in alias_map.items()}
        if lowered in alias_lowered:
            return alias_lowered[lowered]
        # 3. 包含匹配（如 "红色 条纹" -> red；"春秋季" -> spring+autumn 特殊处理交给 pick_list）
        for cn_key, en_val in alias_map.items():
            if cn_key and cn_key in v:
                return en_val
        return default

    def pick_list(value: Any, allowed: list[str], alias_map: dict[str, str]) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_tokens = [t.strip() for t in value.replace("，", ",").replace("、", ",").split(",") if t.strip()]
        elif isinstance(value, list):
            raw_tokens = [str(t).strip() for t in value if isinstance(t, (str, int)) and str(t).strip()]
        else:
            return []
        # 对每个原始 token，若包含特殊组合（如 "春秋"），拆成多个小 token
        tokens: list[str] = []
        for t in raw_tokens:
            # 处理常见中文组合词
            splits: list[str] = []
            if "春秋" in t and ("夏" not in t) and ("冬" not in t):
                splits.append(t.replace("春秋", "春"))
                splits.append(t.replace("春秋", "秋"))
            elif "春夏" in t and ("秋" not in t):
                splits.append(t.replace("春夏", "春"))
                splits.append(t.replace("春夏", "夏"))
            elif "夏秋" in t and ("冬" not in t):
                splits.append(t.replace("夏秋", "夏"))
                splits.append(t.replace("夏秋", "秋"))
            elif "秋冬" in t:
                splits.append(t.replace("秋冬", "秋"))
                splits.append(t.replace("秋冬", "冬"))
            elif "春夏秋" in t or "春秋夏" in t:
                splits.append("春")
                splits.append("夏")
                splits.append("秋")
            else:
                splits.append(t)
            tokens.extend(splits)

        result: list[str] = []
        alias_lk = {k.lower(): val for k, val in alias_map.items()}
        for token in tokens:
            if not token:
                continue
            lowered = token.lower()
            found = None
            # 1. 精确匹配枚举
            for a in allowed:
                if a.lower() == lowered:
                    found = a
                    break
            # 2. 别名精确匹配（中文 key）
            if not found and token in alias_map:
                found = alias_map[token]
            # 3. 别名小写匹配
            if not found and lowered in alias_lk:
                found = alias_lk[lowered]
            # 4. 包含匹配（如 "夏季" -> summer；"适合春天" -> spring）
            if not found:
                for cn_key, en_val in alias_map.items():
                    if cn_key and cn_key in token:
                        found = en_val
                        break
            if found and found not in result:
                result.append(found)
        return result

    result = ClothingRecognizeOut(
        type=pick(data.get("type"), CLOTHING_TYPES, _TYPE_ALIAS, "top"),
        sub_type=pick(data.get("sub_type"), CLOTHING_SUB_TYPES, _TYPE_ALIAS, ""),
        main_color=pick(data.get("main_color"), COLORS, _COLOR_ALIAS, "white"),
        pattern=pick(data.get("pattern"), PATTERNS, _PATTERN_ALIAS, ""),
        season=pick_list(data.get("season"), SEASONS, _SEASON_ALIAS),
        thickness=pick(data.get("thickness"), THICKNESS, _THICKNESS_ALIAS, "normal"),
        style_tags=pick_list(data.get("style_tags"), STYLE_TAGS, _STYLE_ALIAS),
        brand=str(data.get("brand") or "")[:120],
        size=str(data.get("size") or "")[:60],
        confidence=max(0.0, min(1.0, float(data.get("confidence") or 0))),
        notes=str(data.get("notes") or "")[:500],
    )

    # 根据字段完整性重新计算综合置信度
    filled_score = 0.0
    max_score = 0.0
    if result.type and result.type in CLOTHING_TYPES:
        filled_score += RECOGNITION_FIELD_SCORE_META["type"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["type"]["weight"]
    if result.main_color and result.main_color in COLORS:
        filled_score += RECOGNITION_FIELD_SCORE_META["main_color"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["main_color"]["weight"]
    if result.thickness and result.thickness in THICKNESS:
        filled_score += RECOGNITION_FIELD_SCORE_META["thickness"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["thickness"]["weight"]
    if result.pattern and result.pattern in PATTERNS:
        filled_score += RECOGNITION_FIELD_SCORE_META["pattern"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["pattern"]["weight"]
    if result.style_tags:
        filled_score += RECOGNITION_FIELD_SCORE_META["style_tags"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["style_tags"]["weight"]
    if result.season:
        filled_score += RECOGNITION_FIELD_SCORE_META["season"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["season"]["weight"]
    if result.sub_type and result.sub_type in CLOTHING_SUB_TYPES:
        filled_score += RECOGNITION_FIELD_SCORE_META["sub_type"]["weight"]
    max_score += RECOGNITION_FIELD_SCORE_META["sub_type"]["weight"]

    ai_conf = float(data.get("confidence") or 0) if data.get("confidence") else 0.75
    completeness = filled_score / max_score if max_score else 0.0
    result.confidence = round(max(0.0, min(1.0, ai_conf * 0.55 + completeness * 0.45)), 2)
    if not result.notes and completeness < 0.6:
        result.notes = "本次识别部分字段需要人工确认，请检查类别、颜色与厚度。"
    return result


def _recognition_prompt() -> str:
    type_descs = [
        ("top", "上衣（T恤、衬衫、卫衣、毛衣、马甲等）"),
        ("pants", "裤子"),
        ("skirt", "裙子"),
        ("outerwear", "外套（夹克、羽绒服、风衣、大衣等）"),
        ("shoes", "鞋子"),
        ("hat", "帽子"),
        ("accessory", "配饰（围巾、手套、包、发带、袜子、围兜等）"),
        ("set", "套装（上下装一体）"),
        ("innerwear", "内衣（秋衣秋裤、打底衫）"),
        ("babywear", "婴儿服（连体衣、哈衣、爬服）"),
        ("sleepwear", "睡衣/睡袋"),
    ]
    sub_type_descs = [
        ("tshirt", "T恤"), ("shirt", "衬衫"), ("hoodie", "连帽卫衣"), ("sweater", "毛衣/针织衫"),
        ("polo", "Polo衫"), ("vest", "马甲/背心"), ("jeans", "牛仔裤"), ("casual_pants", "休闲裤"),
        ("shorts", "短裤"), ("sweatpants", "运动裤"), ("leggings", "打底裤/紧身裤"),
        ("bib_pants", "背带裤"), ("short_skirt", "短裙"), ("long_skirt", "长裙"), ("dress", "连衣裙"),
        ("tutu", "蓬蓬裙"), ("jacket", "夹克"), ("down_jacket", "羽绒服"), ("windbreaker", "风衣"),
        ("cardigan", "开衫"), ("coat", "大衣"), ("cape", "披风"), ("sneakers", "运动鞋"),
        ("sandals", "凉鞋"), ("boots", "靴子"), ("casual_shoes", "休闲鞋"), ("slippers", "拖鞋"),
        ("toddler_shoes", "学步鞋"), ("crib_shoes", "婴儿鞋"), ("cap", "棒球帽/鸭舌帽"),
        ("bucket_hat", "渔夫帽"), ("beanie", "毛线帽/套头帽"), ("sun_hat", "遮阳帽"),
        ("scarf", "围巾"), ("gloves", "手套"), ("bag", "包/书包"), ("hairband", "发带"),
        ("socks", "袜子"), ("bib", "围兜/口水巾"), ("blanket", "毯子"), ("casual_set", "休闲套装"),
        ("sport_set", "运动套装"), ("formal_set", "正式套装"), ("thermal", "保暖内衣"),
        ("undershirt", "贴身内衣"), ("onesie", "连体哈衣"), ("romper", "短爬服"),
        ("bodysuit", "包屁衣"), ("coverall", "连身服"), ("swaddle", "襁褓"), ("pajamas", "睡衣"),
        ("sleep_sack", "睡袋"), ("robe", "浴袍"),
    ]
    color_descs = [
        ("white", "白色"), ("black", "黑色"), ("gray", "灰色"), ("red", "红色"),
        ("orange", "橙色"), ("yellow", "黄色"), ("green", "绿色"), ("blue", "蓝色"),
        ("purple", "紫色"), ("pink", "粉色"), ("peach", "桃色"), ("mint", "薄荷绿"),
        ("sky_blue", "天蓝色"), ("lavender", "淡紫色"), ("cream", "奶油色"),
        ("beige", "米色"), ("khaki", "卡其色"), ("brown", "棕色"), ("coffee", "咖啡色"),
        ("navy", "藏青色/深蓝色"), ("burgundy", "酒红色"), ("forest_green", "森林绿"),
        ("charcoal", "炭灰色"), ("denim", "牛仔蓝"), ("gold", "金色"), ("silver", "银色"),
        ("neon_green", "荧光绿"), ("multicolor", "多色拼接/印花"),
    ]
    pattern_descs = [
        ("solid", "纯色"), ("stripe", "条纹"), ("plaid", "格纹/格子"), ("print", "印花/图案"),
        ("cartoon", "卡通/动漫人物"), ("floral", "花卉/花朵图案"), ("polka_dot", "波点"),
        ("animal", "动物图案"), ("letter", "字母"), ("number", "数字"), ("star", "星星"),
        ("heart", "爱心"), ("cloud", "云朵"), ("rainbow", "彩虹"), ("dinosaur", "恐龙"),
        ("car", "小汽车"), ("embroidery", "刺绣/绣花"), ("colorblock", "撞色块拼接"),
        ("gradient", "渐变色"), ("contrast", "撞色/强烈对比"), ("leopard", "豹纹"),
    ]
    thickness_descs = [
        ("thin", "薄（夏季单层、网眼、薄棉布）"),
        ("normal", "普通厚度（春秋常规、单层面料）"),
        ("thick", "厚（双层布料、夹棉、厚卫衣）"),
        ("fleece", "加绒/抓绒（内里有绒）"),
    ]
    season_descs = [
        ("spring", "春季"), ("summer", "夏季"), ("autumn", "秋季"),
        ("winter", "冬季"), ("all", "全年可穿"),
    ]
    style_descs = [
        ("casual", "休闲/日常"), ("sporty", "运动风"), ("formal", "正式/礼服"),
        ("cute", "可爱/甜美"), ("cool", "酷帅/潮"), ("korean", "韩系"),
        ("japanese", "日系"), ("preppy", "学院风"), ("minimalist", "简约风"),
    ]

    def _fmt(pairs: list[tuple[str, str]]) -> str:
        return "; ".join(f"{v}={d}" for v, d in pairs)

    lines = [
        "你是专业的儿童衣物识别助手。根据图片，输出一件最显眼衣物的严格 JSON 对象。",
        '【核心要求】所有字段值必须从下面的"英文枚举值"列表中选择，不要输出中文值，不要输出未列出的值！',
        "",
        "type（衣物主类型，必填）：" + _fmt(type_descs),
        "",
        "sub_type（衣物细分类，可选）：" + _fmt(sub_type_descs),
        "",
        "main_color（主颜色，必填）：" + _fmt(color_descs),
        "",
        "pattern（图案，可选）：" + _fmt(pattern_descs),
        "",
        "thickness（厚度，必填）：" + _fmt(thickness_descs),
        "",
        "season（适合季节，数组，元素从以下选择）：" + ", ".join(f"{v}={d}" for v, d in season_descs),
        "",
        "style_tags（风格标签，字符串数组，元素从以下选择）：" + ", ".join(f"{v}={d}" for v, d in style_descs),
        "",
        "【输出格式】严格合法 JSON，字段如下：",
        "{",
        '  "type": "从 type 列表选择的英文枚举值",',
        '  "sub_type": "从 sub_type 列表选择的英文枚举值，不确定返回空字符串",',
        '  "main_color": "从 main_color 列表选择的英文枚举值",',
        '  "pattern": "从 pattern 列表选择的英文枚举值，不确定返回空字符串",',
        '  "season": ["spring", "summer", "autumn", "winter", "all" 中一个或多个，不选返回[]],',
        '  "thickness": "从 thickness 列表选择的英文枚举值",',
        '  "style_tags": ["从 style_tags 列表选择的英文枚举值数组，不选返回[]],',
        '  "brand": "品牌文字，不确定则返回空字符串",',
        '  "size": "尺码文字，不确定则返回空字符串",',
        '  "confidence": 0.0 到 1.0 之间的浮点数，表示你对整体识别结果的自信程度,',
        '  "notes": "对用户的简短提示文字，例如：这是连体衣，适合 1 岁宝宝；或领口有污渍请注意，不确定则返回空字符串"',
        "}",
        "",
        "【示例输出】",
        '{',
        '  "type": "top",',
        '  "sub_type": "hoodie",',
        '  "main_color": "pink",',
        '  "pattern": "stripe",',
        '  "season": ["autumn", "spring"],',
        '  "thickness": "normal",',
        '  "style_tags": ["cute", "casual"],',
        '  "brand": "",',
        '  "size": "100",',
        '  "confidence": 0.85,',
        '  "notes": ""',
        "}",
        "",
        "【最终规则】",
        "1. 若图片中有多件衣物，只识别画面中最显眼、最居中的那一件。",
        "2. 无法确定的字段返回空字符串或空数组，但 type、main_color、thickness 必须尽力识别。",
        "3. 绝对不要凭空臆造品牌、尺码，识别不到就留空。",
        "4. 只返回一个 JSON 对象，不要任何 markdown 标记、不要额外说明文字、不要代码块。",
    ]
    return "\n".join(lines)

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
    request_body = {
        "model": settings.ark_clothing_model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": image_url},
                    {"type": "input_text", "text": _recognition_prompt()},
                ],
            }
        ],
    }
    logger.warning("ark clothing request=%s", json.dumps(_compact_ark_request(request_body), ensure_ascii=False))

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                settings.ark_responses_url,
                headers={
                    "Authorization": f"Bearer {settings.ark_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            logger.warning("ark clothing status_code=%s", response.status_code)
            logger.warning("ark clothing response=%s", response.text[:3000])
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别服务调用失败") from exc

    text = _extract_ark_text(data)
    if not text:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别服务未返回文本")
    logger.warning("ark clothing text=%s", text[:3000])
    result = _normalize_recognition(_pick_recognition_object(_extract_json(text)))
    logger.warning("ark clothing normalized=%s", result.model_dump_json())
    return result


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

