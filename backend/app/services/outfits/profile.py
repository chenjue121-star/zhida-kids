from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Child, Clothing, OutfitDiary, User
from ...style_rules import StyleRuleset

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
    from .scoring import child_age_months
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
