import jwt
import pytest
import httpx


def test_login_same_identity_and_me(client, login, auth):
    one, two = login('alice'), login('alice')
    assert one['user']['id'] == two['user']['id']
    assert isinstance(one['user']['id'], str)
    assert client.get('/v2/me', headers=auth(one)).json() == {'user': one['user'], 'families': [], 'memberships': []}
    assert 'openid' not in one['user']


def test_required_jwt_claims(client, login, auth):
    user = login('alice')
    payload = jwt.decode(user['token'], options={'verify_signature': False})
    for claim in ['iss', 'aud', 'sub', 'iat', 'exp']:
        altered = dict(payload)
        del altered[claim]
        token = jwt.encode(altered, 'test-secret-at-least-thirty-two-bytes', algorithm='HS256')
        assert client.get('/v2/me', headers={'Authorization': 'Bearer ' + token}).status_code == 401
    assert client.get('/v2/me').status_code == 401
    assert client.get('/v2/me', headers={'Authorization': 'Bearer invalid'}).status_code == 401


@pytest.mark.parametrize('mutate', [lambda p: p.update(exp=1), lambda p: p.update(iss='old-app'),
                                  lambda p: p.update(aud='old-client'), lambda p: p.update(sub='not-an-id'),
                                  lambda p: p.update(iat=9999999999)])
def test_invalid_tokens(client, login, mutate):
    payload = jwt.decode(login('alice')['token'], options={'verify_signature': False})
    mutate(payload)
    token = jwt.encode(payload, 'test-secret-at-least-thirty-two-bytes', algorithm='HS256')
    assert client.get('/v2/me', headers={'Authorization': 'Bearer ' + token}).status_code == 401


def test_async_exchange_and_failures(client):
    async def exchange(code):
        if code == 'timeout':
            raise httpx.ReadTimeout('test timeout')
        if code == 'bad':
            return {'errcode': 40029}
        return {'openid': 'async-user', 'session_key': 'never-store-this'}
    client.app.state.wechat_exchange = exchange
    assert client.post('/v2/auth/wechat-login', json={'code': 'ok'}).status_code == 200
    assert client.post('/v2/auth/wechat-login', json={'code': 'bad'}).status_code == 400
    assert client.post('/v2/auth/wechat-login', json={'code': 'timeout'}).status_code == 503


def test_wechat_transport_no_external_calls():
    import asyncio
    from app.v2.core.config import V2Settings
    from app.v2.integrations.wechat import exchange_code
    settings = V2Settings(_env_file=None, database_url='sqlite://', jwt_secret='test',
                          wechat_appid='test-app', wechat_secret='test-secret', dev_wechat_mock=False)
    def handler(request):
        assert request.url.params['grant_type'] == 'authorization_code'
        return httpx.Response(200, json={'openid': 'remote-identity', 'session_key': 'discard'})
    assert asyncio.run(exchange_code('fresh-code', settings, transport=httpx.MockTransport(handler))) == {'openid': 'remote-identity', 'nickname': ''}


@pytest.mark.parametrize('provider_code', [40013, 40125, 40164])
def test_wechat_configuration_errors_are_not_invalid_user_codes(client, provider_code):
    client.app.state.wechat_exchange = lambda code: {'errcode': provider_code}
    result = client.post('/v2/auth/wechat-login', json={'code': 'new-login-code'})
    assert result.status_code == 503
    assert result.json()['error']['code'] == 'WECHAT_CONFIGURATION_ERROR'
