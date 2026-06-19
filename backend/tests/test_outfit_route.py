# Characterization tests for POST /outfits/recommend.
# These lock the CURRENT behavior of the route before refactoring.
# Schema notes:
#   - OutfitRecommendIn fields: child_id (int), scene (str, default="school"),
#     weather (WeatherSnapshot | None), exclude_clothing_ids (List[int]),
#     locked_clothing_ids (List[int]), replace_group (str).
#     There is NO `temperature` field — weather is a nested object.
#   - OutfitRecommendOut: source (str), warnings (List[str]), cached (bool), etc.
# Payload adjustments vs. the task template:
#   - Dropped `temperature` (doesn't exist); kept `scene` (valid optional field).
#   - No exclude_clothing_ids / locked_clothing_ids so the cache path is active.


def _recommend_payload(child_id):
    # Minimal valid payload: only child_id is required; scene defaults to "school".
    # We omit exclude/locked ids so the route's cache logic is triggered.
    return {"child_id": child_id, "scene": "school"}


def test_recommend_fallback_when_ai_unavailable(client, monkeypatch):
    """When call_ai_recommend returns None and dev_outfit_mock is False,
    source must be 'fallback' and warnings must contain the fallback notice."""
    async def _no_ai(*args, **kwargs):
        return None

    monkeypatch.setattr("app.routers.outfits.call_ai_recommend", _no_ai)
    monkeypatch.setattr("app.routers.outfits.settings.dev_outfit_mock", False)

    child_id = client.seed["child_id"]
    resp = client.post("/outfits/recommend", json=_recommend_payload(child_id))
    assert resp.status_code == 200
    body = resp.json()
    # source == "fallback" when dev_outfit_mock is False and AI is unavailable
    assert body["source"] == "fallback"
    # Warning text (line 932 of outfits.py): "AI 推荐暂不可用，已使用审美策略规则兜底。"
    assert any("兜底" in w for w in body.get("warnings", []))


def test_recommend_empty_wardrobe_400(client, db_session, monkeypatch):
    """With no active clothing, the route must return 400 with the Chinese error detail."""
    from app.models import Clothing

    db_session.query(Clothing).delete()
    db_session.commit()

    child_id = client.seed["child_id"]
    resp = client.post("/outfits/recommend", json=_recommend_payload(child_id))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "衣橱暂无可推荐衣物"


def test_recommend_cache_hit_returns_same(client, db_session, monkeypatch):
    """The second identical request (same child, scene, weather, no exclude/locked)
    must be served from cache — call_ai_recommend is called at most once total.

    Characterization note: OutfitRecommendation rows persist across tests within
    the same session (conftest.seed only clears User/Child/Clothing, not OutfitRecommendation).
    So if a prior test already wrote a cache row for this child+date+cache_key, the
    first call here also hits cache (calls["n"] == 0). We therefore assert <= 1, which
    covers both: (a) fresh run — first call computes, second hits cache; (b) prior
    cache row exists — both calls hit cache immediately.
    The key invariant is that the second call is always served from cache (cached==True)
    and the AI is never called more than once.
    """
    from app.models import OutfitRecommendation

    # Clear any existing recommendation cache for this child so we get a clean slate.
    child_id = client.seed["child_id"]
    db_session.query(OutfitRecommendation).filter(
        OutfitRecommendation.child_id == child_id
    ).delete()
    db_session.commit()

    calls = {"n": 0}

    async def _counting_ai(*args, **kwargs):
        calls["n"] += 1
        return None

    monkeypatch.setattr("app.routers.outfits.call_ai_recommend", _counting_ai)
    monkeypatch.setattr("app.routers.outfits.settings.dev_outfit_mock", False)

    first = client.post("/outfits/recommend", json=_recommend_payload(child_id))
    second = client.post("/outfits/recommend", json=_recommend_payload(child_id))
    assert first.status_code == second.status_code == 200
    # Cache is only active when exclude_clothing_ids and locked_clothing_ids are empty.
    # The first call stores the result; the second must hit the cache without calling AI again.
    assert calls["n"] == 1
    # The cached response has cached==True
    assert second.json()["cached"] is True
