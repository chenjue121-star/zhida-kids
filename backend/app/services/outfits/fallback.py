from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ...models import Child, Clothing, User
from ...schemas import OutfitRecommendIn, OutfitRecommendOut, WeatherSnapshot
from ...style_rules import StyleRuleset
from .profile import choose_style_profile
from .scoring import child_age_months, enrich_reason, pick_best

CORE_GROUPS = {
    "top": ["top", "innerwear", "babywear"],
    "bottom": ["pants", "skirt", "set"],
    "shoes": ["shoes"],
}
OPTIONAL_GROUPS = {
    "outerwear": ["outerwear"],
    "accessory": ["hat", "accessory", "sleepwear"],
}


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
