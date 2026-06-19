from __future__ import annotations

import json
import logging
from typing import List, Optional

import httpx
from sqlalchemy.orm import Session

from ...config import settings
from ...models import Child, Clothing, User
from ...schemas import OutfitRecommendIn, WeatherSnapshot
from ...style_rules import StyleRuleset
from .ai_build import extract_json
from .cache import compact_clothing
from .profile import choose_style_profile
from .scoring import child_age_months

logger = logging.getLogger(__name__)


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
