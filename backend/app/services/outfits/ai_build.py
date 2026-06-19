from __future__ import annotations

import json
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from ...models import Child, Clothing, User
from ...schemas import OutfitRecommendIn, OutfitRecommendOut
from ...style_rules import StyleRuleset
from .fallback import build_fallback_outfit
from .profile import choose_style_profile
from .scoring import child_age_months


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
