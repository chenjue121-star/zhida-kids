from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..deps import ensure_child_owned
from ..models import Clothing, OutfitRecommendation, User
from ..schemas import OutfitRecommendIn, OutfitRecommendOut
from ..style_rules import get_current_ruleset
from ..services.outfits.cache import (
    build_cache_signature,
    cache_to_outfit,
    upsert_recommendation_cache,
)
from ..services.outfits.fallback import build_fallback_outfit
from ..services.outfits.ai_build import build_ai_outfit
from ..services.outfits.ai_client import call_ai_recommend
from ..services.outfits.scoring import recent_clothing_counts

router = APIRouter(prefix="/outfits", tags=["outfits"])


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
