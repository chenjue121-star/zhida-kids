from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Clothing, OutfitRecommendation
from ...schemas import OutfitRecommendIn, OutfitRecommendOut, WeatherSnapshot
from ...style_rules import StyleRuleset
from ...models import Child


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
