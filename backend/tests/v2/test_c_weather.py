import importlib.util


def forecast():
    assert importlib.util.find_spec('app.v2.weather.forecast') is not None, 'target-day forecast is missing'
    from app.v2.weather import forecast
    return forecast


def test_official_daily_forecast_selects_actual_local_target_not_other_day():
    data = {'metadata': {'tag': 'timestamp-independent'}, 'days': [{
        'forecastStartTime': '2026-10-03T00:00+08:00', 'forecastEndTime': '2026-10-04T00:00+08:00',
        'temperatureMin': {'value': 20, 'unit': '°C'}, 'temperatureMax': {'value': 29, 'unit': '°C'},
        'daytime': {'condition': {'text': '晴', 'code': '100'}, 'humidity': 0.5,
                    'precipitation': {'probability': 0.1}, 'wind': {'speed': {'value': 2, 'unit': 'm/s'}}}}]}
    first = forecast().normalize(data, '2026-10-03', 'Asia/Shanghai', {'city': '上海', 'lat': 31.23, 'lon': 121.47})
    assert first['status'] == 'known' and first['temp_min'] == 20 and first['humidity'] == 50
    assert forecast().normalize(data, '2026-10-04', 'Asia/Shanghai', {'city': '上海'})['status'] == 'unknown'


def test_forecast_timestamp_does_not_change_effective_conditions_and_nonfinite_is_unknown():
    data = {'days': [{'forecastStartTime': '2026-10-02T16:00Z',
        'temperatureMin': {'value': float('nan')}, 'temperatureMax': {'value': 29},
        'daytime': {'condition': {'text': '晴'}}}]}
    assert forecast().normalize(data, '2026-10-03', 'Asia/Shanghai', {'city': '上海'})['status'] == 'unknown'


def test_fetch_uses_official_daily_endpoint_and_local_time_without_current_weather():
    from app.v2.core.config import V2Settings
    settings = V2Settings(_env_file=None, database_url='sqlite://', jwt_secret='forecast-test-only', env='test',
                          qweather_api_host='https://forecast.example.test', qweather_api_key='fake-test-key')
    calls = []
    def get(url, headers):
        calls.append((url, headers))
        if '/geo/' in url:
            return {'location': [{'name': '上海', 'lat': '31.23', 'lon': '121.47'}]}
        return {'days': [{'forecastStartTime': '2026-10-03T00:00+08:00',
            'temperatureMin': {'value': 20}, 'temperatureMax': {'value': 25},
            'daytime': {'condition': {'text': '晴', 'code': '100'}}}]}
    result = forecast().fetch(settings, {'city': '上海', 'target_date': '2026-10-03',
        'timezone': 'Asia/Shanghai', 'lat': None, 'lon': None}, get)
    assert result['status'] == 'known'
    assert '/weather/v1/daily/31.23/121.47?' in calls[1][0]
    assert 'localTime=true' in calls[1][0]
    assert all('/current/' not in url for url, _ in calls)
    assert all(headers == {'X-QW-Api-Key': 'fake-test-key'} for _, headers in calls)
