"""Target-day forecasts. QWeather official daily endpoint, never current weather."""
from datetime import datetime, timezone
from math import isfinite
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx


def unknown(target_date, location):
    return {'status': 'unknown', 'target_date': str(target_date), 'city': location.get('city'),
            'lat': location.get('lat'), 'lon': location.get('lon'), 'source': None,
            'message': '目标日天气暂未知，请家长核对衣物适宜性'}


def finite(value):
    number = float(value)
    if not isfinite(number):
        raise ValueError('Nonfinite forecast')
    return number


def normalize(data, target_date, timezone_name, location):
    result = unknown(target_date, location)
    if not isinstance(data, dict):
        return result
    for day in data.get('days') or []:
        try:
            daytime = day.get('daytime') or {}
            stamp = daytime.get('forecastStartTime') or day['forecastStartTime']
            instant = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=ZoneInfo(timezone_name))
            if instant.astimezone(ZoneInfo(timezone_name)).date().isoformat() != str(target_date):
                continue
            low, high = finite(day['temperatureMin']['value']), finite(day['temperatureMax']['value'])
            if low > high or not -90 <= low <= high <= 65:
                raise ValueError('Invalid forecast temperature')
            condition = daytime.get('condition') or {}
            if not isinstance(condition.get('text'), str) or not condition['text'].strip():
                raise ValueError('Missing condition')
            values = {'temp_min': round(low, 1), 'temp_max': round(high, 1),
                      'condition': condition['text'], 'condition_code': str(condition.get('code', ''))}
            for field, value, maximum, scale in (
                ('humidity', daytime.get('humidity'), 1, 100),
                ('precipitation_probability', (daytime.get('precipitation') or {}).get('probability'), 1, 100),
                ('wind_speed', ((daytime.get('wind') or {}).get('speed') or {}).get('value'), 150, 1),
            ):
                if value is not None:
                    value = finite(value)
                    if not 0 <= value <= maximum:
                        raise ValueError('Invalid forecast condition')
                    values[field] = round(value * scale, 1)
            return {**result, **values, 'status': 'known', 'source': 'qweather',
                    'attributions': (data.get('metadata') or {}).get('attributions', [])}
        except (KeyError, TypeError, ValueError, OverflowError):
            return result
    return result


def fetch(settings, payload, getter=None):
    location = {k: payload.get(k) for k in ('city', 'lat', 'lon')}
    target = payload['target_date']
    if not settings.qweather_api_host or not settings.qweather_api_key.get_secret_value():
        return unknown(target, location)
    host = settings.qweather_api_host.rstrip('/')
    headers = {'X-QW-Api-Key': settings.qweather_api_key.get_secret_value()}
    def get(path, params):
        url = host + path + '?' + urlencode(params)
        if getter is not None:
            return getter(url, headers)
        response = httpx.get(url, headers=headers, timeout=8)
        response.raise_for_status()
        return response.json()
    try:
        if location['lat'] is None:
            if not location['city']:
                return unknown(target, location)
            places = get('/geo/v2/city/lookup', {'location': location['city'], 'lang': 'zh'}).get('location') or []
            if not places:
                return unknown(target, location)
            location.update(city=places[0]['name'], lat=finite(places[0]['lat']), lon=finite(places[0]['lon']))
        lat, lon = finite(location['lat']), finite(location['lon'])
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            return unknown(target, location)
        # https://dev.qweather.com/en/docs/api/weather/weather-daily-forecast/
        data = get(f'/weather/v1/daily/{lat:.2f}/{lon:.2f}', {'days': 10, 'localTime': 'true', 'lang': 'zh'})
        return normalize(data, target, payload['timezone'], location)
    except (httpx.HTTPError, KeyError, TypeError, ValueError, OverflowError):
        return unknown(target, location)
