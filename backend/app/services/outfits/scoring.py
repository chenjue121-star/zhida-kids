from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Child, Clothing, OutfitDiary
from ...schemas import OutfitRecommendIn, WeatherSnapshot
from ...style_rules import StyleRuleset

SCENE_LABELS = {
    "home": "日常在家",
    "school": "上学",
    "outdoor": "户外活动",
    "shopping": "外出逛街",
    "party": "聚会派对",
    "travel": "度假出行",
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
