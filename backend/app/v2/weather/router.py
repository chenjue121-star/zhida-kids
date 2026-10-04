from __future__ import annotations

from math import isfinite
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Query, Request

from app.v2.core.errors import fail
from app.v2.identity.tokens import current_user

router = APIRouter()


def _fetch(request: Request, path: str, query: dict | None = None) -> dict:
    settings = request.app.state.settings
    host = settings.qweather_api_host.rstrip('/')
    key = settings.qweather_api_key.get_secret_value()
    if not host or not key:
        fail(503, 'WEATHER_UNAVAILABLE', '天气服务尚未配置，请稍后重试')
    url = host + path + ('?' + urlencode(query) if query else '')
    headers = {'X-QW-Api-Key': key}
    try:
        if hasattr(request.app.state, 'weather_get'):
            data = request.app.state.weather_get(url, headers)
        else:
            response = httpx.get(url, headers=headers, timeout=8)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        fail(503, 'WEATHER_UNAVAILABLE', '天气服务暂不可用，请稍后重试')
    if not isinstance(data, dict) or (data.get('code') and data['code'] != '200'):
        fail(503, 'WEATHER_UNAVAILABLE', '天气服务暂不可用，请稍后重试')
    return data


def _locations(request: Request, term: str) -> list[dict]:
    data = _fetch(request, '/geo/v2/city/lookup', {'location': term, 'lang': 'zh'})
    result = []
    for item in data.get('location') or []:
        try:
            result.append({'name': item['name'], 'region': item.get('adm1') or '',
                           'lat': float(item['lat']), 'lon': float(item['lon'])})
        except (KeyError, TypeError, ValueError):
            continue
    return result


@router.get('/location/search')
def search_city(request: Request, city: str = Query(..., min_length=1, max_length=80), user=Depends(current_user)):
    return _locations(request, city.strip())


@router.get('/weather/current')
def current_weather(request: Request, city: str | None = Query(None, min_length=1, max_length=80),
                    lat: float | None = Query(None, ge=-90, le=90),
                    lon: float | None = Query(None, ge=-180, le=180), user=Depends(current_user)):
    if (lat is None) != (lon is None) or (lat is None and not city):
        fail(422, 'LOCATION_REQUIRED', '请选择城市或允许定位')
    term = f'{lon:.2f},{lat:.2f}' if lat is not None else city.strip()
    places = _locations(request, term)
    if not places:
        fail(404, 'CITY_NOT_FOUND', '未找到该城市，请重新选择')
    place = places[0]
    data = _fetch(request, f"/weather/v1/current/{place['lat']}/{place['lon']}", {'lang': 'zh'})
    try:
        temp = float(data['temperature']['value'])
        condition = str(data['condition']['text'])
        moisture = float(data['humidity'])
        if not condition or not isfinite(temp) or not isfinite(moisture) or not 0 <= moisture <= 1:
            raise ValueError('invalid weather')
        humidity = round(moisture * 100)
    except (KeyError, TypeError, ValueError):
        fail(503, 'WEATHER_UNAVAILABLE', '天气数据暂不可用，请稍后重试')
    return {'city': place['name'], 'temp': round(temp), 'weather': condition,
            'humidity': humidity, 'source': 'qweather'}
