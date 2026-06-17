import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional

from ..auth import get_current_user
from ..config import settings
from ..models import User
from ..schemas import WeatherOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weather", tags=["weather"])


def build_suggestion(temp: int, weather: str) -> str:
    if "雨" in weather:
        return "可能有雨，建议准备雨具并选择防滑鞋"
    if temp >= 28:
        return "适宜薄款透气衣物"
    if temp >= 20:
        return "温度舒适，适合常规厚度衣物"
    if temp >= 10:
        return "天气偏凉，建议准备外套"
    return "注意保暖，建议加厚或加绒衣物"


def _fallback_weather(city_name: str) -> WeatherOut:
    """上游天气服务异常时的兜底返回：避免页面因天气挂掉整体白屏。"""
    return WeatherOut(
        city=city_name or "当前位置",
        temp=24,
        weather="暂无实时天气",
        humidity=50,
        suggestion="天气服务暂不可用，建议根据体感择衣",
    )


async def city_to_location(city: str) -> tuple[str, str]:
    params = {"location": city, "key": settings.qweather_api_key}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get("https://geoapi.qweather.com/v2/city/lookup", params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("qweather geo lookup failed: %s", exc)
        raise

    locations = data.get("location") or []
    if not locations:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到城市天气信息")
    first = locations[0]
    return first["id"], first.get("name") or city


@router.get("/current", response_model=WeatherOut)
async def current_weather(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    city: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> WeatherOut:
    city_name = city or current_user.city or "当前位置"

    if not settings.qweather_api_key:
        # 未配置 key：直接返回兜底，避免页面空白
        logger.warning("qweather_api_key not configured, returning fallback weather")
        return _fallback_weather(city_name)

    try:
        if lat is not None and lon is not None:
            location = f"{lon},{lat}"
        else:
            location, city_name = await city_to_location(city_name)
    except HTTPException:
        logger.warning("qweather city lookup 404 for %s, fallback", city_name)
        return _fallback_weather(city_name)
    except Exception as exc:  # noqa: BLE001
        logger.exception("qweather city lookup failed for %s", city_name)
        return _fallback_weather(city_name)

    params = {"location": location, "key": settings.qweather_api_key}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get("https://devapi.qweather.com/v7/weather/now", params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("qweather now lookup failed: %s", exc)
        return _fallback_weather(city_name)

    now = data.get("now") or {}
    if not now:
        logger.warning("qweather now empty for %s", location)
        return _fallback_weather(city_name)

    try:
        temp = int(float(now.get("temp", 0)))
        weather = now.get("text") or ""
        humidity = int(float(now.get("humidity", 0)))
    except (TypeError, ValueError) as exc:
        logger.warning("qweather parse failed: %s raw=%r", exc, now)
        return _fallback_weather(city_name)

    return WeatherOut(
        city=city_name,
        temp=temp,
        weather=weather,
        humidity=humidity,
        suggestion=build_suggestion(temp, weather),
    )
