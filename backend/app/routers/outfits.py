from __future__ import annotations

import json
import logging
import hashlib
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..deps import ensure_child_owned
from ..models import Child, Clothing, OutfitDiary, OutfitRecommendation, User
from ..schemas import OutfitRecommendIn, OutfitRecommendOut, WeatherSnapshot
from ..style_rules import StyleRuleset, get_current_ruleset

router = APIRouter(prefix="/outfits", tags=["outfits"])
logger = logging.getLogger(__name__)

CORE_GROUPS = {
    "top": ["top", "innerwear", "babywear"],
    "bottom": ["pants", "skirt", "set"],
    "shoes": ["shoes"],
}
OPTIONAL_GROUPS = {
    "outerwear": ["outerwear"],
    "accessory": ["hat", "accessory", "sleepwear"],
}
SCENE_LABELS = {
    "home": "日常在家",
    "school": "上学",
    "outdoor": "户外活动",
    "shopping": "外出逛街",
    "party": "聚会派对",
    "travel": "度假出行",
}

# ---------------------------------------------------------------------------
# 风格 profile ↔ style_tag 映射（用于将用户选择/衣橱/日记 反馈 翻译成 profile 得分）
# 这些 tag 同时也是前端 STYLE_TAGS 和 clothing.style_tags 使用的枚举值。
# ---------------------------------------------------------------------------

PROFILE_TO_TAGS: dict[str, set[str]] = {
    "clean_comfort": {"casual", "minimalist", "preppy"},
    "soft_nature": {"cute", "korean", "japanese"},
    "sporty_play": {"sporty", "casual", "cool"},
    "retro_fun": {"cute", "cool", "casual"},
    "toddler_soft": {"cute"},
}

TAG_TO_PROFILES: dict[str, set[str]] = {}
for _profile, _tags in PROFILE_TO_TAGS.items():
    for _t in _tags:
        TAG_TO_PROFILES.setdefault(_t, set()).add(_profile)

# 每个 profile 在不同场景下的固定基础分（保留原启发式的直观性）
PROFILE_SCENE_BASE: dict[str, dict[str, int]] = {
    "home": {"retro_fun": 10, "clean_comfort": 8, "toddler_soft": 6},
    "school": {"clean_comfort": 12, "preppy": 8, "sporty_play": 6},
    "outdoor": {"sporty_play": 18, "clean_comfort": 6},
    "shopping": {"soft_nature": 14, "retro_fun": 6},
    "party": {"soft_nature": 12, "retro_fun": 10},
    "travel": {"soft_nature": 14, "sporty_play": 8},
}


def child_age_months(child: Child) -> int:
    today = date.today()
    months = (today.year - child.birthday.year) * 12 + today.month - child.birthday.month
    if today.day < child.birthday.day:
        months -= 1
    return max(months, 0)


def current_season() -> str:
    month = date.today().month
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def recommended_thickness(temp: int) -> str:
    if temp >= 28:
        return "thin"
    if temp >= 20:
        return "normal"
    if temp >= 10:
        return "thick"
    return "fleece"


# ---------------------------------------------------------------------------
# 偏好学习: 多信号加权计分
# ---------------------------------------------------------------------------

def _profile_scores_from_user_tags(
    user_tags: list[str], available_profiles: list[str], weight: int = 15
) -> dict[str, int]:
    """用户显式偏好（onboarding / profile 页选择的 style_tags）。"""
    scores: dict[str, int] = {p: 0 for p in available_profiles}
    if not user_tags:
        return scores
    for tag in user_tags:
        for profile in TAG_TO_PROFILES.get(tag, set()):
            if profile in scores:
                scores[profile] += weight
    return scores


def _profile_scores_from_wardrobe(
    clothing_list: list[Clothing], available_profiles: list[str], max_bonus: int = 10
) -> dict[str, int]:
    """衣橱中衣物 style_tags 的分布 → 倾向于用户实际购买的风格。"""
    scores: dict[str, int] = {p: 0 for p in available_profiles}
    if not clothing_list:
        return scores
    tag_counts: dict[str, int] = {}
    total_with_tags = 0
    for item in clothing_list:
        tags = item.style_tags or []
        if not tags:
            continue
        total_with_tags += 1
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    if total_with_tags == 0:
        return scores
    # 按每个 tag 的占比给相关 profile 加基础分，上限 max_bonus
    for tag, count in tag_counts.items():
        ratio = count / total_with_tags
        for profile in TAG_TO_PROFILES.get(tag, set()):
            if profile in scores:
                scores[profile] += int(round(ratio * max_bonus))
    return scores


def _profile_scores_from_feedback(
    db: Session,
    child: Child,
    clothing_by_id: dict[int, Clothing],
    available_profiles: list[str],
    history_days: int = 60,
    good_rating_weight: int = 12,
    bad_rating_penalty: int = -10,
    good_mood_bonus: int = 5,
) -> dict[str, int]:
    """根据穿搭日记的 rating / mood 反推 profile 得分 —— 即『学习』用户偏好。

    规则:
      - 最近 history_days 天内 rating >= 4 的穿搭 → 相关 profile +good_rating_weight
      - rating <= 2 → 相关 profile +bad_rating_penalty
      - mood ∈ {"happy", "love", "满意", "喜欢"} → 额外 +good_mood_bonus
    """
    scores: dict[str, int] = {p: 0 for p in available_profiles}
    if not clothing_by_id:
        return scores

    try:
        from datetime import date as _date, timedelta as _td

        start = _date.today() - _td(days=history_days)
        diaries = list(
            db.scalars(
                select(OutfitDiary).where(
                    OutfitDiary.child_id == child.id, OutfitDiary.date >= start
                )
            )
        )
    except Exception:
        return scores

    if not diaries:
        return scores

    good_moods = {"happy", "love", "满意", "喜欢", "开心", "很喜欢", "great", "good"}
    for diary in diaries:
        cids = getattr(diary, "clothing_ids", None) or []
        if not cids:
            continue
        tags_in_outfit: set[str] = set()
        for cid in cids:
            item = clothing_by_id.get(int(cid))
            if item and item.style_tags:
                tags_in_outfit.update(item.style_tags)
        if not tags_in_outfit:
            continue
        # 决定本次日记的强度
        rating = getattr(diary, "rating", 0) or 0
        mood = (getattr(diary, "mood", "") or "").lower()
        delta = 0
        if rating >= 4:
            delta += good_rating_weight
            if any(m in mood or m in (getattr(diary, "mood", "") or "") for m in good_moods):
                delta += good_mood_bonus
        elif 0 < rating <= 2:
            delta += bad_rating_penalty
        if delta == 0:
            continue
        for tag in tags_in_outfit:
            for profile in TAG_TO_PROFILES.get(tag, set()):
                if profile in scores:
                    scores[profile] += delta
    return scores


def _profile_scores_from_scene_and_meta(
    scene: str, child: Child, ruleset: StyleRuleset, available_profiles: list[str]
) -> dict[str, int]:
    """场景 / 年龄 / 天气的静态规则基础分。"""
    scores: dict[str, int] = {p: 0 for p in available_profiles}

    # 场景的固定基础分（保留原启发式的直观性）
    for profile, bonus in PROFILE_SCENE_BASE.get(scene, {}).items():
        if profile in scores:
            scores[profile] += bonus

    # scene_rules.prefer_style_tags → 映射到 profile
    scene_rule = ruleset.scene_rules.get(scene)
    if scene_rule:
        for tag in scene_rule.prefer_style_tags:
            for profile in TAG_TO_PROFILES.get(tag, set()):
                if profile in scores:
                    scores[profile] += 8

    # 年龄: 0-3 岁 toddler_soft 更强
    age_months = child_age_months(child)
    if age_months <= 36 and "toddler_soft" in scores:
        scores["toddler_soft"] += 20
    if age_months > 36 and "toddler_soft" in scores:
        scores["toddler_soft"] -= 10

    return scores


def choose_style_profile(
    ruleset: StyleRuleset,
    child: Child,
    scene: str,
    clothing_list: list[Clothing],
    db: Session,
    current_user: Optional[User] = None,
) -> tuple[str, dict[str, int]]:
    """**学习型** profile 选择: 汇总 4 路信号 → 选最高分。

    返回 (profile_key, 原始分数字典)，方便调试/记录。
    """
    available = [p for p in ruleset.style_profiles if p in PROFILE_TO_TAGS] or list(ruleset.style_profiles)
    if not available:
        return ("", {})

    clothing_by_id = {c.id: c for c in clothing_list if c.status == "active"}
    active_clothing = list(clothing_by_id.values())

    # 1. 用户显式偏好
    user_tags: list[str] = []
    if current_user is not None:
        user_tags = list(getattr(current_user, "style_preference", None) or [])
    user_scores = _profile_scores_from_user_tags(user_tags, available)

    # 2. 衣橱分布
    wardrobe_scores = _profile_scores_from_wardrobe(active_clothing, available)

    # 3. 历史反馈 (日记 rating/mood)
    feedback_scores = _profile_scores_from_feedback(db, child, clothing_by_id, available)

    # 4. 场景 + 年龄 + 规则
    meta_scores = _profile_scores_from_scene_and_meta(scene, child, ruleset, available)

    # 汇总
    scores: dict[str, int] = {}
    for p in available:
        scores[p] = (
            user_scores.get(p, 0)
            + wardrobe_scores.get(p, 0)
            + feedback_scores.get(p, 0)
            + meta_scores.get(p, 0)
        )

    # 选出最高分；若全部为 0（全新用户），退回 clean_comfort
    if not scores or max(scores.values()) <= 0:
        fallback = "clean_comfort" if "clean_comfort" in ruleset.style_profiles else next(
            iter(ruleset.style_profiles), ""
        )
        return (fallback, scores)

    best = max(scores, key=lambda k: scores[k])
    return (best, scores)


# ---------------------------------------------------------------------------
# 衣物单项评分（保留原有逻辑，但改为接收 profile_key 而非再自己选）
# ---------------------------------------------------------------------------


def recent_clothing_counts(db: Session, child_id: int) -> Dict[int, int]:
    start = date.today() - timedelta(days=21)
    diaries = db.scalars(
        select(OutfitDiary).where(OutfitDiary.child_id == child_id, OutfitDiary.date >= start)
    )
    counts: Dict[int, int] = {}
    for diary in diaries:
        age_days = (date.today() - diary.date).days
        if age_days <= 2:
            penalty = 5
        elif age_days <= 7:
            penalty = 3
        elif age_days <= 14:
            penalty = 1
        else:
            penalty = 0
        for clothing_id in diary.clothing_ids or []:
            counts[int(clothing_id)] = counts.get(int(clothing_id), 0) + penalty
    return counts


def score_item(
    item: Clothing,
    payload: OutfitRecommendIn,
    ruleset: StyleRuleset,
    style_profile_key: str,
    recent_counts: Dict[int, int],
) -> int:
    weather = payload.weather or WeatherSnapshot()
    season = current_season()
    thickness = recommended_thickness(weather.temp)
    weights = ruleset.scoring_rules.weights
    score = 0
    if item.thickness == thickness:
        score += weights.get("weather_match", 30)
    elif item.thickness in ("normal", "thin") and thickness in ("normal", "thin"):
        score += weights.get("weather_match", 30) // 2
    if "all" in (item.season or []) or season in (item.season or []):
        score += 12

    scene_rule = ruleset.scene_rules.get(payload.scene)
    if scene_rule:
        if set(item.style_tags or []) & set(scene_rule.prefer_style_tags):
            score += weights.get("scene_match", 25)
        if item.type in scene_rule.avoid_types or item.sub_type in scene_rule.avoid_types:
            score += weights.get("unsafe_or_inconvenient_penalty", -15)

    profile = ruleset.style_profiles.get(style_profile_key)
    if profile:
        if item.type in profile.preferred_types:
            score += weights.get("style_consistency", 15)
        if item.main_color in profile.preferred_colors:
            score += weights.get("color_harmony", 20)
        if item.pattern in profile.preferred_patterns:
            score += 6
        if item.pattern in profile.avoid_patterns:
            score -= 8

    # 显式排除 / 锁定优先 / 近期重复
    if item.id in payload.exclude_clothing_ids:
        score -= 25
    recent_penalty = recent_counts.get(item.id, 0) * weights.get("recent_repeat_penalty", -10)
    score += recent_penalty
    # 穿着过多次的衣物做适度惩罚（每穿 10 次 -2，最多 -20）
    wear_count = int(item.wear_count or 0)
    score -= min(20, (wear_count // 10) * 2)
    return score


def enrich_reason(
    items: List[Clothing],
    payload: OutfitRecommendIn,
    style_profile_key: str,
    ruleset: StyleRuleset,
    source: str,
) -> tuple[str, str]:
    weather = payload.weather or WeatherSnapshot()
    scene_name = SCENE_LABELS.get(payload.scene, payload.scene)
    profile = ruleset.style_profiles.get(style_profile_key)
    profile_label = profile.label if profile else "舒适日常"
    reason = f"今天{weather.city or '当前位置'}{weather.temp}°C，{weather.weather or '天气信息有限'}，按{scene_name}场景选择了{profile_label}方向。"
    if profile and profile.prompt_hint:
        reason += profile.prompt_hint
    if items:
        colors = [item.main_color for item in items if item.main_color]
        if colors:
            reason += "整体颜色控制在清爽协调的范围内，方便宝宝活动。"
    if source != "ai":
        reason += "智能推荐暂不可用时，已使用审美策略规则兜底。"
    tips = weather.suggestion or "请按宝宝实际体感微调厚度。"
    return reason, tips


def pick_best(
    candidates: List[Clothing],
    types: List[str],
    payload: OutfitRecommendIn,
    ruleset: StyleRuleset,
    style_profile_key: str,
    recent_counts: Dict[int, int],
    used_ids: set[int],
) -> Optional[Clothing]:
    pool = [item for item in candidates if item.type in types and item.id not in used_ids]
    if not pool:
        return None
    return max(pool, key=lambda item: score_item(item, payload, ruleset, style_profile_key, recent_counts))


def build_fallback_outfit(
    child: Child,
    clothing: List[Clothing],
    payload: OutfitRecommendIn,
    ruleset: StyleRuleset,
    *,
    source: str = "fallback",
    warnings: Optional[List[str]] = None,
    recent_counts: Optional[Dict[int, int]] = None,
    db: Optional[Session] = None,
    current_user: Optional[User] = None,
) -> OutfitRecommendOut:
    warnings = warnings or []
    # 新的学习型 profile 选择：优先使用学习型 choose_style_profile，失败时退回旧版启发式
    try:
        if db is not None:
            style_profile_key, profile_scores = choose_style_profile(
                ruleset, child, payload.scene, clothing, db, current_user
            )
        else:
            style_profile_key, profile_scores = "", {}
    except Exception:
        style_profile_key, profile_scores = "", {}
    if not style_profile_key:
        # 旧版启发式兜底（保持向后兼容）
        age = child_age_months(child)
        if age <= 36 and "toddler_soft" in ruleset.style_profiles:
            style_profile_key = "toddler_soft"
        elif payload.scene == "outdoor" and "sporty_play" in ruleset.style_profiles:
            style_profile_key = "sporty_play"
        elif payload.scene in {"shopping", "travel", "party"} and "soft_nature" in ruleset.style_profiles:
            style_profile_key = "soft_nature"
        elif payload.scene == "home" and "retro_fun" in ruleset.style_profiles:
            style_profile_key = "retro_fun"
        else:
            style_profile_key = "clean_comfort" if "clean_comfort" in ruleset.style_profiles else next(
                iter(ruleset.style_profiles), ""
            )
    recent_counts = recent_counts or {}
    candidates = [item for item in clothing if item.status == "active"]
    if not candidates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="衣橱暂无可推荐衣物")

    locked = [item for item in candidates if item.id in payload.locked_clothing_ids]
    selected: List[Clothing] = []
    used_ids: set[int] = set()
    for item in locked:
        if item.id not in used_ids:
            selected.append(item)
            used_ids.add(item.id)

    for types in CORE_GROUPS.values():
        if any(item.type in types for item in selected):
            continue
        item = pick_best(candidates, types, payload, ruleset, style_profile_key, recent_counts, used_ids)
        if item:
            selected.append(item)
            used_ids.add(item.id)

    weather = payload.weather or WeatherSnapshot()
    if weather.temp < 20 and not any(item.type == "outerwear" for item in selected):
        outer = pick_best(candidates, OPTIONAL_GROUPS["outerwear"], payload, ruleset, style_profile_key, recent_counts, used_ids)
        if outer:
            selected.append(outer)
            used_ids.add(outer.id)
    if len(selected) < 4:
        accessory = pick_best(candidates, OPTIONAL_GROUPS["accessory"], payload, ruleset, style_profile_key, recent_counts, used_ids)
        if accessory:
            selected.append(accessory)

    missing = []
    for group, types in CORE_GROUPS.items():
        if not any(item.type in types for item in selected):
            missing.append(group)
    if missing:
        warnings.append(f"核心单品不足：{', '.join(missing)}")
    if not selected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="衣物不足，无法生成推荐")

    reason, tips = enrich_reason(selected, payload, style_profile_key, ruleset, source)
    return OutfitRecommendOut(
        items=selected,
        reason=reason,
        tips=tips,
        scene=payload.scene,
        date=date.today(),
        weather=payload.weather,
        source=source,
        warnings=warnings,
        style_profile=style_profile_key,
        ruleset_id=ruleset.meta.id,
        ruleset_version=ruleset.meta.version,
    )


def extract_json(text: str) -> dict:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("AI 未返回文本")

    # 去除 markdown code fence
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        stripped = []
        in_fence = False
        fence_seen = False
        for line in lines:
            if line.strip().startswith("```"):
                if not fence_seen:
                    in_fence = True
                    fence_seen = True
                else:
                    in_fence = False
                continue
            if fence_seen and not in_fence:
                break
            stripped.append(line)
        cleaned = "\n".join(stripped).strip()

    # 寻找匹配的花括号
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("AI 文本不含 JSON 对象")

    depth = 0
    in_string = False
    escape_next = False
    end_idx = -1
    for i in range(start, len(cleaned)):
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
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i + 1
                break
    if end_idx <= start:
        raise ValueError("AI 文本 JSON 括号不匹配")

    candidate = cleaned[start:end_idx]
    return json.loads(candidate)


def compact_clothing(item: Clothing) -> dict:
    return {
        "id": item.id,
        "type": item.type,
        "sub_type": item.sub_type,
        "main_color": item.main_color,
        "pattern": item.pattern,
        "season": item.season or [],
        "thickness": item.thickness,
        "style_tags": item.style_tags or [],
        "wear_count": item.wear_count or 0,
        "last_worn_at": item.last_worn_at.isoformat() if item.last_worn_at else "",
    }


def clothing_fingerprint(clothing: List[Clothing]) -> list[dict]:
    return [
        {
            "id": item.id,
            "updated_at": item.updated_at.isoformat() if item.updated_at else "",
            "status": item.status,
            "wear_count": item.wear_count or 0,
            "last_worn_at": item.last_worn_at.isoformat() if item.last_worn_at else "",
        }
        for item in sorted(clothing, key=lambda c: c.id)
        if item.status == "active"
    ]


def build_cache_signature(
    child: Child,
    clothing: List[Clothing],
    payload: OutfitRecommendIn,
    ruleset: StyleRuleset,
) -> tuple[str, dict]:
    weather = payload.weather or WeatherSnapshot()
    signature = {
        "child_id": child.id,
        "date": date.today().isoformat(),
        "scene": payload.scene,
        "weather": {
            "city": weather.city or "",
            "temp": weather.temp,
            "weather": weather.weather or "",
            "humidity": weather.humidity,
        },
        "clothing": clothing_fingerprint(clothing),
        "ruleset": {"id": ruleset.meta.id, "version": ruleset.meta.version},
    }
    raw = json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), signature


def outfit_to_cache(outfit: OutfitRecommendOut) -> dict:
    data = outfit.model_dump(mode="json")
    data["items"] = [item.model_dump(mode="json") for item in outfit.items]
    return data


def cache_to_outfit(data: dict) -> OutfitRecommendOut:
    payload = dict(data or {})
    payload["cached"] = True
    outfit = OutfitRecommendOut.model_validate(payload)
    # 增强缓存命中提示
    cache_tip = "这是今日该场景的缓存推荐。若需要重新计算，请刷新或调整排除项。"
    if isinstance(outfit.tips, str):
        outfit.tips = f"{outfit.tips} {cache_tip}".strip()
    elif isinstance(outfit.tips, list):
        outfit_copy = list(outfit.tips)
        outfit_copy.append(cache_tip)
        outfit.tips = outfit_copy
    return outfit


def upsert_recommendation_cache(
    db: Session,
    child: Child,
    cache_key: str,
    signature: dict,
    outfit: OutfitRecommendOut,
) -> None:
    today = date.today()
    existing = db.scalar(
        select(OutfitRecommendation).where(
            OutfitRecommendation.child_id == child.id,
            OutfitRecommendation.date == today,
            OutfitRecommendation.cache_key == cache_key,
        )
    )
    response = outfit_to_cache(outfit)
    response["cached"] = False
    if existing is None:
        db.add(
            OutfitRecommendation(
                child_id=child.id,
                date=today,
                cache_key=cache_key,
                request_signature=signature,
                response=response,
                source=outfit.source,
            )
        )
    else:
        existing.request_signature = signature
        existing.response = response
        existing.source = outfit.source
    db.commit()


def compact_gptsapi_request(request_body: dict) -> dict:
    compact = dict(request_body)
    messages = compact.get("messages") or []
    compact_messages = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            content_preview = content[:3000]
        else:
            content_preview = str(content)[:3000]
        compact_messages.append({"role": message.get("role"), "content": content_preview})
    compact["messages"] = compact_messages
    return compact


async def call_ai_recommend(
    child: Child,
    clothing: List[Clothing],
    payload: OutfitRecommendIn,
    ruleset: StyleRuleset,
    *,
    db: Optional[Session] = None,
    current_user: Optional[User] = None,
) -> Optional[dict]:
    if settings.dev_outfit_mock or not settings.gptsapi_api_key:
        return None

    try:
        if db is not None:
            style_profile_key, _ = choose_style_profile(
                ruleset, child, payload.scene, clothing, db, current_user
            )
        else:
            style_profile_key = ""
    except Exception:
        style_profile_key = ""
    if not style_profile_key:
        age = child_age_months(child)
        if age <= 36 and "toddler_soft" in ruleset.style_profiles:
            style_profile_key = "toddler_soft"
        elif payload.scene == "outdoor" and "sporty_play" in ruleset.style_profiles:
            style_profile_key = "sporty_play"
        elif payload.scene in {"shopping", "travel", "party"} and "soft_nature" in ruleset.style_profiles:
            style_profile_key = "soft_nature"
        elif payload.scene == "home" and "retro_fun" in ruleset.style_profiles:
            style_profile_key = "retro_fun"
        else:
            style_profile_key = "clean_comfort" if "clean_comfort" in ruleset.style_profiles else next(
                iter(ruleset.style_profiles), ""
            )
    profile = ruleset.style_profiles.get(style_profile_key)
    prompt = {
        "task": "从给定儿童衣橱候选中选择一套穿搭，只返回 JSON object。",
        "required_json_keys": ["clothing_ids", "reason", "tips", "warnings"],
        "rules": [
            "只能选择候选列表中存在的 clothing id，不要创造衣物。",
            "优先儿童舒适、安全、方便活动。",
            "必须考虑天气、场景、颜色协调、厚度、近期不重复。",
            "clothing_ids 至少包含上衣/下装/鞋子中能满足库存的核心项。",
        ],
        "child": {
            "nickname": child.nickname,
            "gender": child.gender,
            "age_months": child_age_months(child),
            "height": child.height,
            "weight": child.weight,
        },
        "scene": payload.scene,
        "weather": (payload.weather or WeatherSnapshot()).model_dump(),
        "style_ruleset": {
            "id": ruleset.meta.id,
            "version": ruleset.meta.version,
            "style_profile": style_profile_key,
            "profile_hint": profile.prompt_hint if profile else "",
            "prompt_guidelines": ruleset.prompt_guidelines,
        },
        "exclude_clothing_ids": payload.exclude_clothing_ids,
        "locked_clothing_ids": payload.locked_clothing_ids,
        "candidates": [compact_clothing(item) for item in clothing[:80]],
    }
    request_body = {
        "model": settings.gptsapi_model,
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
    }
    logger.warning("outfit gptsapi request=%s", json.dumps(compact_gptsapi_request(request_body), ensure_ascii=False))
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                settings.gptsapi_base_url,
                headers={
                    "Authorization": f"Bearer {settings.gptsapi_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            logger.warning("outfit gptsapi status_code=%s", response.status_code)
            logger.warning("outfit gptsapi response=%s", response.text[:3000])
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.warning("outfit ai call failed: %s", exc)
        return None

    # 兼容多种响应结构
    text = ""
    if isinstance(data, dict):
        if isinstance(data.get("content"), list):
            for block in data["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    text += block.get("text", "")
        if not text and isinstance(data.get("content"), str):
            text = data["content"]
        if not text and isinstance(data.get("text"), str):
            text = data["text"]
        if not text and isinstance(data.get("output"), str):
            text = data["output"]
        if not text:
            # 尝试 openai-style: choices -> message -> content
            for choice in data.get("choices") or []:
                if isinstance(choice, dict):
                    msg = choice.get("message") or choice.get("delta")
                    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                        text += msg["content"]
    if not text:
        logger.warning("outfit gptsapi returned no text: %s", json.dumps(data, ensure_ascii=False)[:3000])
        return None
    logger.warning("outfit gptsapi text=%s", text[:3000])
    try:
        result = extract_json(text)
        logger.warning("outfit gptsapi parsed=%s", json.dumps(result, ensure_ascii=False)[:3000])
        return result
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("outfit ai json parse failed: %s raw=%r", exc, text[:2000])
        return None


def build_ai_outfit(
    ai_data: dict,
    child: Child,
    clothing: List[Clothing],
    payload: OutfitRecommendIn,
    ruleset: StyleRuleset,
    *,
    db: Optional[Session] = None,
    current_user: Optional[User] = None,
) -> Optional[OutfitRecommendOut]:
    ids = ai_data.get("clothing_ids") or []
    if not isinstance(ids, list):
        return None
    by_id = {item.id: item for item in clothing if item.status == "active"}
    selected: List[Clothing] = []
    for raw_id in ids:
        try:
            clothing_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        item = by_id.get(clothing_id)
        if item and item.id not in {i.id for i in selected}:
            selected.append(item)
    if not selected:
        return None

    # 新的学习型 profile 选择（带降级）
    try:
        if db is not None:
            style_profile_key, _ = choose_style_profile(
                ruleset, child, payload.scene, clothing, db, current_user
            )
        else:
            style_profile_key = ""
    except Exception:
        style_profile_key = ""
    if not style_profile_key:
        age = child_age_months(child)
        if age <= 36 and "toddler_soft" in ruleset.style_profiles:
            style_profile_key = "toddler_soft"
        elif payload.scene == "outdoor" and "sporty_play" in ruleset.style_profiles:
            style_profile_key = "sporty_play"
        elif payload.scene in {"shopping", "travel", "party"} and "soft_nature" in ruleset.style_profiles:
            style_profile_key = "soft_nature"
        elif payload.scene == "home" and "retro_fun" in ruleset.style_profiles:
            style_profile_key = "retro_fun"
        else:
            style_profile_key = "clean_comfort" if "clean_comfort" in ruleset.style_profiles else next(
                iter(ruleset.style_profiles), ""
            )

    fallback = build_fallback_outfit(
        child, clothing, payload, ruleset, source="ai", db=db, current_user=current_user
    )
    selected_ids = {item.id for item in selected}
    for item in fallback.items:
        if item.id not in selected_ids and len(selected) < 5:
            selected.append(item)
            selected_ids.add(item.id)

    return OutfitRecommendOut(
        items=selected,
        reason=str(ai_data.get("reason") or fallback.reason),
        tips=str(ai_data.get("tips") or fallback.tips),
        scene=payload.scene,
        date=date.today(),
        weather=payload.weather,
        source="ai",
        warnings=[str(item) for item in (ai_data.get("warnings") or []) if item],
        style_profile=style_profile_key,
        ruleset_id=ruleset.meta.id,
        ruleset_version=ruleset.meta.version,
    )


@router.post("/recommend", response_model=OutfitRecommendOut)
async def recommend_outfit(
    payload: OutfitRecommendIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutfitRecommendOut:
    child = ensure_child_owned(db, current_user, payload.child_id)
    clothing = list(db.scalars(select(Clothing).where(Clothing.child_id == child.id, Clothing.status == "active")))
    if not clothing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="衣橱暂无可推荐衣物")

    ruleset = get_current_ruleset()
    cache_key, signature = build_cache_signature(child, clothing, payload, ruleset)
    should_use_cache = not payload.exclude_clothing_ids and not payload.locked_clothing_ids
    if should_use_cache:
        cached = db.scalar(
            select(OutfitRecommendation).where(
                OutfitRecommendation.child_id == child.id,
                OutfitRecommendation.date == date.today(),
                OutfitRecommendation.cache_key == cache_key,
            )
        )
        if cached is not None:
            return cache_to_outfit(cached.response)

    recent_counts = recent_clothing_counts(db, child.id)
    ai_data = await call_ai_recommend(child, clothing, payload, ruleset, db=db, current_user=current_user)
    if ai_data:
        ai_outfit = build_ai_outfit(
            ai_data, child, clothing, payload, ruleset, db=db, current_user=current_user
        )
        if ai_outfit:
            upsert_recommendation_cache(db, child, cache_key, signature, ai_outfit)
            return ai_outfit

    source = "mock" if settings.dev_outfit_mock else "fallback"
    warnings = [] if settings.dev_outfit_mock else ["AI 推荐暂不可用，已使用审美策略规则兜底。"]
    outfit = build_fallback_outfit(
        child,
        clothing,
        payload,
        ruleset,
        source=source,
        warnings=warnings,
        recent_counts=recent_counts,
        db=db,
        current_user=current_user,
    )
    upsert_recommendation_cache(db, child, cache_key, signature, outfit)
    return outfit
