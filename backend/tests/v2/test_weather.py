from app.v2.core.config import V2Settings
from app.v2.main import create_app
from fastapi.testclient import TestClient


def test_weather_requires_configuration(client, login, auth):
    response = client.get('/v2/weather/current?city=上海', headers=auth(login('weather-user')))
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'WEATHER_UNAVAILABLE'


def test_city_search_and_current_weather(engine):
    calls = []

    def get(url, headers):
        calls.append((url, headers))
        if '/geo/v2/city/lookup' in url:
            return {'code': '200', 'location': [{'name': '上海', 'adm1': '上海市', 'lat': '31.2300', 'lon': '121.4700'}]}
        return {'code': '200', 'temperature': {'value': 27}, 'condition': {'text': '晴'}, 'humidity': 0.55}

    settings = V2Settings(_env_file=None, database_url='sqlite://', jwt_secret='test-secret-at-least-thirty-two-bytes',
                          env='test', qweather_api_host='https://weather.example.com', qweather_api_key='secret')
    app = create_app(settings, engine, lambda code: {'openid': code, 'nickname': code})
    app.state.weather_get = get
    with TestClient(app) as client:
        identity = client.post('/v2/auth/wechat-login', json={'code': 'weather-user'}).json()
        headers = {'Authorization': 'Bearer ' + identity['token']}
        cities = client.get('/v2/location/search?city=上海', headers=headers)
        assert cities.status_code == 200
        assert cities.json()[0]['name'] == '上海'
        weather = client.get('/v2/weather/current?city=上海', headers=headers)
        assert weather.status_code == 200
        assert weather.json() == {'city': '上海', 'temp': 27, 'weather': '晴', 'humidity': 55, 'source': 'qweather'}
        located = client.get('/v2/weather/current?lat=31.23&lon=121.47', headers=headers)
        assert located.status_code == 200
        assert located.json()['city'] == '上海'
    assert all(headers == {'X-QW-Api-Key': 'secret'} for _, headers in calls)


def test_weather_rejects_bad_location(client, login, auth):
    headers = auth(login('location-user'))
    assert client.get('/v2/weather/current?lat=200&lon=121', headers=headers).status_code == 422
    assert client.get('/v2/weather/current', headers=headers).status_code == 422
